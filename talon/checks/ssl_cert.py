"""5.5 ssl_cert: certificate valid for the host, not expiring, issued by the same CA as before."""

from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime

from .. import messages as M
from ..config import Site
from ..context import Context
from ..models import CheckResult, Status

STATE_FILE = "ssl.json"
CERT_TIME = "%b %d %H:%M:%S %Y %Z"


def _issuer_org(cert: dict) -> str:
    for rdn in cert.get("issuer", ()):
        for key, value in rdn:
            if key in ("organizationName", "commonName"):
                if key == "organizationName":
                    return value
    for rdn in cert.get("issuer", ()):
        for key, value in rdn:
            if key == "commonName":
                return value
    return "?"


def _sans(cert: dict) -> list[str]:
    return [value for key, value in cert.get("subjectAltName", ()) if key == "DNS"]


def probe(host: str, port: int = 443, timeout: float = 10.0) -> dict:
    """Open a TLS connection with SNI and read the certificate. Network I/O lives only here."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert() or {}
        return {
            "verified": True,
            "issuer": _issuer_org(cert),
            "not_after": cert.get("notAfter"),
            "sans": _sans(cert),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - report, never raise into the run
        info = {"verified": False, "issuer": None, "not_after": None, "sans": [],
                "error": f"{type(exc).__name__}: {exc}"[:200]}
        # read the certificate anyway, so we can say *why* it does not fit
        try:
            relaxed = ssl.create_default_context()
            relaxed.check_hostname = False
            relaxed.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with relaxed.wrap_socket(sock, server_hostname=host) as tls:
                    der = tls.getpeercert(binary_form=True)
            if der:
                import os
                import tempfile

                with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
                    fh.write(ssl.DER_cert_to_PEM_cert(der))
                    pem_path = fh.name
                try:
                    # stdlib helper: parses a PEM file into the same dict getpeercert() returns
                    cert = ssl._ssl._test_decode_cert(pem_path)  # noqa: SLF001
                finally:
                    os.unlink(pem_path)
                info["issuer"] = _issuer_org(cert)
                info["not_after"] = cert.get("notAfter")
                info["sans"] = _sans(cert)
        except Exception:  # noqa: BLE001 - best effort only
            pass
        return info


def _days_left(not_after: str | None, now: datetime) -> int | None:
    if not not_after:
        return None
    try:
        expires = datetime.strptime(not_after, CERT_TIME).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (expires - now.astimezone(UTC)).days


def _covers(host: str, sans: list[str]) -> bool:
    for san in sans:
        if san == host:
            return True
        if san.startswith("*.") and host.count(".") == san.count(".") and host.endswith(san[1:]):
            return True
    return False


def run(ctx: Context, site: Site) -> list[CheckResult]:
    probe_fn = ctx.ssl_probe or probe
    stored = ctx.state.read_json(site.name, STATE_FILE) or {}
    fresh: dict[str, dict] = {}
    out: list[CheckResult] = []

    for host in site.hosts:
        info = probe_fn(host, 443)
        # could not read the certificate at all -> one retry, same rule as HTTP (a flaky network
        # must not look like a broken certificate)
        if not info.get("verified") and not info.get("sans"):
            ctx.fetcher.sleep(ctx.config.retry_after_seconds)
            retry = probe_fn(host, 443)
            if retry.get("verified") or retry.get("sans"):
                info = retry
            info["retried"] = True
        sans = info.get("sans") or []
        days = _days_left(info.get("not_after"), ctx.now)

        if not info.get("verified"):
            if sans and not _covers(host, sans):
                out.append(CheckResult("ssl", site.name, Status.FAIL, M.S_HOSTNAME.format(host=host),
                                       {"host": host, "sans": sans, "error": info.get("error")}))
            elif not sans:
                # nothing came back at all: the host did not answer, which is not the same
                # as a certificate that fails verification
                out.append(CheckResult("ssl", site.name, Status.FAIL,
                                       M.S_UNREACHABLE.format(host=host, error=info.get("error")),
                                       {"host": host, "error": info.get("error"), "retried": True}))
            else:
                out.append(CheckResult("ssl", site.name, Status.FAIL,
                                       M.S_INVALID.format(host=host, error=info.get("error")),
                                       {"host": host, "error": info.get("error")}))
            continue

        if not _covers(host, sans) and sans:
            out.append(CheckResult("ssl", site.name, Status.FAIL, M.S_HOSTNAME.format(host=host),
                                   {"host": host, "sans": sans}))

        fresh[host] = {"issuer": info.get("issuer"), "not_after": info.get("not_after")}

        if days is not None:
            if days < ctx.config.ssl_fail_days:
                out.append(CheckResult("ssl", site.name, Status.FAIL, M.S_EXPIRING.format(days=days, host=host),
                                       {"host": host, "days": days}))
            elif days < ctx.config.ssl_warn_days:
                out.append(CheckResult("ssl", site.name, Status.WARN, M.S_EXPIRING.format(days=days, host=host),
                                       {"host": host, "days": days}))
            else:
                out.append(CheckResult("ssl", site.name, Status.OK, M.S_OK.format(days=days, host=host),
                                       {"host": host, "days": days, "issuer": info.get("issuer")}))

        old = stored.get(host, {})
        old_issuer = old.get("issuer")
        new_issuer = info.get("issuer")
        if old_issuer is None:
            out.append(CheckResult("ssl", site.name, Status.INFO,
                                   M.S_BASELINE.format(host=host, issuer=new_issuer or "?"),
                                   {"host": host, "issuer": new_issuer}))
        elif new_issuer != old_issuer and new_issuer not in ctx.config.allowed_issuers:
            out.append(CheckResult("ssl", site.name, Status.FAIL,
                                   M.S_ISSUER.format(host=host, old=old_issuer, new=new_issuer),
                                   {"host": host, "old": old_issuer, "new": new_issuer}, changed=True))

    if ctx.save_state and fresh:
        merged = {**stored, **fresh}
        ctx.state.write_json(site.name, STATE_FILE, merged)
    return out
