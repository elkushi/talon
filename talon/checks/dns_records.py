"""5.6 dns_records: records must match what we expect, or at least what they were yesterday.

Module name is dns_records.py on purpose: a module called dns.py would shadow dnspython.
"""

from __future__ import annotations

from datetime import datetime

import dns.rdatatype
import dns.resolver

from .. import messages as M
from ..config import DnsDomain
from ..context import Context
from ..models import CheckResult, Status

STATE_FILE = "dns.json"
HARD_TYPES = {"A", "AAAA", "CNAME", "MX", "NS"}   # a change here is FAIL
SOFT_TYPES = {"TXT", "CAA"}                        # a change here is WARN
HOST_TYPES = ["A", "AAAA", "CNAME"]                # what we ask about subdomains
RDAP_URL = "https://rdap.org/domain/{domain}"
TIMEOUT = 5.0


def query(name: str, rtype: str, resolver_ip: str | None = None) -> list[str]:
    """One DNS question. resolver_ip None = ask the zone's authoritative nameserver."""
    resolver = dns.resolver.Resolver(configure=resolver_ip is None)
    resolver.timeout = TIMEOUT
    resolver.lifetime = TIMEOUT * 2
    if resolver_ip:
        resolver.nameservers = [resolver_ip]
    else:
        resolver.nameservers = _authoritative_ips(name) or resolver.nameservers
    try:
        answer = resolver.resolve(name, rtype, raise_on_no_answer=False)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    rrset = answer.rrset
    if rrset is None:
        return []
    return sorted(rr.to_text() for rr in rrset)


def _authoritative_ips(name: str) -> list[str]:
    """IPs of the nameservers for the closest zone above `name`."""
    labels = name.split(".")
    base = dns.resolver.Resolver()
    base.timeout = TIMEOUT
    base.lifetime = TIMEOUT * 2
    for i in range(len(labels) - 1):
        zone = ".".join(labels[i:])
        try:
            ns_answer = base.resolve(zone, "NS")
        except Exception:  # noqa: BLE001 - try the next zone up
            continue
        ips: list[str] = []
        for ns in ns_answer:
            try:
                ips += [rr.to_text() for rr in base.resolve(ns.target.to_text(), "A")]
            except Exception:  # noqa: BLE001
                continue
        if ips:
            return ips
    return []


def rdap(ctx: Context, domain: str) -> dict | None:
    """Registrar view of the domain. Many ccTLDs (.kg, .uz, .bd) do not publish RDAP."""
    fetch = ctx.fetcher.request(RDAP_URL.format(domain=domain))
    if fetch.response is None or fetch.response.status_code != 200:
        return None
    try:
        data = fetch.response.json()
    except ValueError:
        return None
    registrar = None
    for entity in data.get("entities") or []:
        if "registrar" in (entity.get("roles") or []):
            for item in (entity.get("vcardArray") or [None, []])[1]:
                if item and item[0] == "fn":
                    registrar = item[3]
    expiry = None
    for event in data.get("events") or []:
        if event.get("eventAction") in ("expiration", "registrar expiration"):
            expiry = event.get("eventDate")
    return {
        "registrar": registrar,
        "nameservers": sorted((ns.get("ldhName") or "").lower() for ns in (data.get("nameservers") or [])),
        "expiry": expiry,
        "status": sorted(data.get("status") or []),
    }


def _days_until(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return (when - now).days


def run(ctx: Context, domain: DnsDomain, hosts: list[str] | None = None) -> list[CheckResult]:
    query_fn = ctx.dns_query or query
    out: list[CheckResult] = []
    stored = ctx.state.read_json(domain.name, STATE_FILE) or {}
    old_records: dict = stored.get("records", {})
    new_records: dict[str, dict[str, list[str]]] = {}
    first_run = not old_records

    targets: list[tuple[str, list[str]]] = [(domain.name, ctx.config.record_types)]
    for host in hosts or []:
        if host != domain.name:
            targets.append((host, HOST_TYPES))

    for name, types in targets:
        new_records.setdefault(name, {})
        for rtype in types:
            answers: dict[str, list[str]] = {}
            failures: list[str] = []
            for resolver_ip in [*ctx.config.resolvers, None]:
                key = resolver_ip or "authoritative"
                try:
                    answers[key] = query_fn(name, rtype, resolver_ip)
                except Exception as exc:  # noqa: BLE001 - one dead resolver is not a dead run
                    failures.append(f"{key}: {type(exc).__name__}")
            if not answers:
                out.append(
                    CheckResult("dns", domain.name, Status.WARN,
                                M.D_ERROR.format(rtype=f"{name} {rtype}", error="; ".join(failures)),
                                {"name": name, "type": rtype, "errors": failures})
                )
                continue

            authoritative = answers.get("authoritative")
            values = authoritative if authoritative else next(iter(answers.values()))
            new_records[name][rtype] = values

            others = {k: v for k, v in answers.items() if k != "authoritative"}
            if authoritative is not None and any(v != authoritative for v in others.values()):
                out.append(
                    CheckResult("dns", domain.name, Status.WARN,
                                M.D_DISAGREE.format(rtype=f"{name} {rtype}"),
                                {"name": name, "type": rtype, "answers": answers})
                )

            severity = Status.FAIL if rtype in HARD_TYPES else Status.WARN
            expected = (domain.expected or {}).get(rtype) if name == domain.name else None
            if expected is not None:
                if sorted(expected) != values:
                    out.append(
                        CheckResult("dns", domain.name, severity,
                                    M.D_UNEXPECTED.format(rtype=f"{name} {rtype}",
                                                          actual=", ".join(values) or "—",
                                                          expected=", ".join(sorted(expected))),
                                    {"name": name, "type": rtype, "actual": values, "expected": expected},
                                    changed=True)
                    )
                continue

            previous = (old_records.get(name) or {}).get(rtype)
            if previous is not None and previous != values:
                out.append(
                    CheckResult("dns", domain.name, severity,
                                M.D_CHANGED.format(rtype=f"{name} {rtype}",
                                                   old=", ".join(previous) or "—",
                                                   new=", ".join(values) or "—"),
                                {"name": name, "type": rtype, "old": previous, "new": values},
                                changed=True)
                )

    rdap_snapshot = stored.get("rdap")
    if ctx.config.rdap_enabled:
        fresh = (ctx.rdap_fetch or (lambda d: rdap(ctx, d)))(domain.name)
        if fresh is None:
            out.append(CheckResult("dns", domain.name, Status.INFO, M.D_RDAP_NONE, {"domain": domain.name}))
        else:
            old = rdap_snapshot or {}
            if old.get("registrar") and fresh.get("registrar") != old.get("registrar"):
                out.append(
                    CheckResult("dns", domain.name, Status.FAIL,
                                M.D_RDAP_REGISTRAR.format(old=old["registrar"], new=fresh.get("registrar")),
                                {"old": old, "new": fresh}, changed=True)
                )
            if old.get("nameservers") and fresh.get("nameservers") != old.get("nameservers"):
                out.append(
                    CheckResult("dns", domain.name, Status.FAIL,
                                M.D_RDAP_NS.format(old=", ".join(old["nameservers"]),
                                                   new=", ".join(fresh.get("nameservers") or [])),
                                {"old": old, "new": fresh}, changed=True)
                )
            days = _days_until(fresh.get("expiry"), ctx.now)
            if days is not None and days < 30:
                out.append(
                    CheckResult("dns", domain.name, Status.WARN,
                                M.D_RDAP_EXPIRY.format(days=days, date=fresh.get("expiry")),
                                {"expiry": fresh.get("expiry"), "days": days})
                )
            rdap_snapshot = fresh

    if first_run:
        out.append(CheckResult("dns", domain.name, Status.INFO, M.D_BASELINE, {"records": new_records}))

    if ctx.save_state and new_records:
        ctx.state.write_json(domain.name, STATE_FILE, {
            "records": new_records,
            "rdap": rdap_snapshot,
            "checked_at": ctx.now.isoformat(timespec="seconds"),
        })

    if not out:
        out.append(CheckResult("dns", domain.name, Status.OK, M.D_OK, {"names": list(new_records)}))
    return out
