"""Runs the checks for a mode and collects the results. No printing, no sending."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime

from . import messages as M
from .checks import content as content_check
from .checks import dns_records, headers, pages, redirects, robots, sitemap, ssl_cert
from .config import Config, DnsDomain, Site
from .context import Context
from .models import CheckResult, Status

log = logging.getLogger(__name__)

SITE_CHECKS = {
    "redirects": redirects.run,
    "robots": robots.run,
    "sitemap": sitemap.run,
    "pages": pages.run,
    "ssl": ssl_cert.run,
    "content": content_check.run,
    "headers": headers.run,
}

DAILY = ("redirects", "robots", "sitemap", "pages", "ssl", "content", "headers")
WATCH = ("content", "ssl")  # dns runs per domain, added separately


def _hosts_for(config: Config, domain: str) -> list[str]:
    hosts: list[str] = []
    for site in config.sites:
        for host in site.hosts:
            if (host == domain or host.endswith("." + domain)) and host not in hosts:
                hosts.append(host)
    return hosts


def _safe(check: str, domain: str, fn, *args) -> list[CheckResult]:
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - a broken check must not kill the run
        log.error("check %s failed for %s:\n%s", check, domain, traceback.format_exc())
        return [
            CheckResult(check, domain, Status.FAIL,
                        M.CHECK_CRASHED.format(check=check, exc=type(exc).__name__),
                        {"traceback": traceback.format_exc()[-2000:]})
        ]


def _watch_filter(results: list[CheckResult]) -> list[CheckResult]:
    """In watch mode the SSL check only reports a changed issuer or a broken certificate."""
    kept: list[CheckResult] = []
    for r in results:
        if r.check != "ssl":
            kept.append(r)
        elif r.changed or (r.status is Status.FAIL and "days" not in r.details):
            kept.append(r)
    return kept


def run(ctx: Context, mode: str) -> list[CheckResult]:
    config = ctx.config
    results: list[CheckResult] = []
    wanted = DAILY if mode == "daily" else WATCH

    for site in config.sites:
        if site.canonical.strip().startswith("TODO"):
            results.append(
                CheckResult("config", site.name, Status.INFO, M.SITE_SKIPPED.format(name=site.name),
                            {"reason": "canonical is TODO"})
            )
            continue
        for check in site.checks:
            if check not in wanted:
                continue
            log.info("%s: %s", site.name, check)
            results += _safe(check, site.name, SITE_CHECKS[check], ctx, site)

    for domain in config.dns_domains:
        log.info("%s: dns", domain.name)
        results += _safe("dns", domain.name, dns_records.run, ctx, domain, _hosts_for(config, domain.name))

    if mode == "watch":
        results = _watch_filter(results)
    return results


def accept(ctx: Context, spec: str) -> list[str]:
    """--accept <domain>/<check>: drop one baseline so the next run records the new state."""
    if "/" not in spec:
        raise ValueError("use --accept <domain>/<check>, e.g. example.org/dns")
    domain, check = spec.split("/", 1)
    return ctx.state.accept(domain.strip(), check.strip())


def summary(results: list[CheckResult]) -> dict:
    counts = {str(s): sum(1 for r in results if r.status is s) for s in Status}
    return {"results": len(results), **counts}


def site_names(config: Config) -> list[str]:
    return [s.name for s in config.sites]


__all__ = ["run", "accept", "summary", "site_names", "Context", "Config", "Site", "DnsDomain", "datetime"]
