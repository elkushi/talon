"""5.1 redirects: every variant must make exactly one permanent hop to the canonical origin."""

from __future__ import annotations

from .. import messages as M
from ..config import Site
from ..context import Context
from ..http import Chain
from ..models import CheckResult, Status


def _norm(url: str | None) -> str:
    if not url:
        return ""
    return url.rstrip("/") + "/"


def _result(site: Site, status: Status, summary: str, chain: Chain, **extra) -> CheckResult:
    details = {"chain": chain.as_dict(), **extra}
    if chain.retried:
        details["note"] = M.RETRY_OK if chain.final_status else chain.error
    return CheckResult("redirects", site.name, status, summary, details)


def _judge(site: Site, url: str, chain: Chain, target: str, is_canonical: bool) -> list[CheckResult]:
    if chain.tls_error:
        return [_result(site, Status.FAIL, M.R_TLS.format(url=url, error=chain.error), chain)]
    if chain.error:
        return [_result(site, Status.FAIL, M.R_DEAD.format(url=url, error=chain.error), chain)]
    if chain.loop:
        return [_result(site, Status.FAIL, M.R_LOOP.format(url=url), chain)]

    if is_canonical:
        if chain.redirect_hops:
            return [
                _result(
                    site,
                    Status.FAIL,
                    M.R_CANONICAL_REDIRECTS.format(url=url, target=chain.final_url),
                    chain,
                )
            ]
        if chain.final_status != 200:
            return [_result(site, Status.FAIL, M.R_BAD_FINAL.format(url=url, status=chain.final_status), chain)]
        return [_result(site, Status.OK, M.R_CANONICAL_OK.format(url=url), chain)]

    # plain http served directly, no redirect at all
    if chain.redirect_hops == 0 and url.startswith("http://"):
        return [
            _result(site, Status.FAIL, M.R_NO_HTTPS.format(url=url, status=chain.final_status), chain)
        ]
    if _norm(chain.final_url) != _norm(target):
        return [
            _result(
                site,
                Status.FAIL,
                M.R_WRONG_TARGET.format(url=url, final=chain.final_url, target=target),
                chain,
            )
        ]
    if chain.final_status != 200:
        return [_result(site, Status.FAIL, M.R_BAD_FINAL.format(url=url, status=chain.final_status), chain)]

    out: list[CheckResult] = []
    if chain.temporary_used:
        status_code = next(h.status for h in chain.hops if h.status in {302, 303, 307})
        out.append(_result(site, Status.WARN, M.R_TEMP.format(url=url, status=status_code), chain))
    if chain.redirect_hops > 1:
        out.append(_result(site, Status.WARN, M.R_MANY_HOPS.format(url=url, hops=chain.redirect_hops), chain))
    if not out:
        out.append(_result(site, Status.OK, M.R_OK.format(url=url, target=target), chain))
    return out


def run(ctx: Context, site: Site) -> list[CheckResult]:
    target = _norm(site.canonical)
    results: list[CheckResult] = []

    chain = ctx.fetcher.walk(target)
    results += _judge(site, target, chain, target, is_canonical=True)

    for variant in site.variants:
        if _norm(variant) == target:
            continue
        chain = ctx.fetcher.walk(variant)
        results += _judge(site, variant, chain, target, is_canonical=False)

    for old, new in site.legacy_redirects.items():
        old_url = site.url(old)
        new_url = _norm(site.url(new))
        chain = ctx.fetcher.walk(old_url)
        problem = None
        if chain.error:
            problem = chain.error
        elif chain.loop:
            problem = "петля"
        elif _norm(chain.final_url) != new_url:
            problem = f"ведёт на {chain.final_url}"
        elif chain.final_status != 200:
            problem = f"код {chain.final_status}"
        elif chain.permanent_hops == 0:
            problem = "переход не постоянный (301/308)"
        if problem:
            results.append(
                _result(
                    site,
                    Status.FAIL,
                    M.R_LEGACY_BAD.format(path=old, target=new_url, problem=problem),
                    chain,
                )
            )
        else:
            results.append(
                _result(site, Status.OK, M.R_LEGACY_OK.format(path=old, target=new_url), chain)
            )
    return results
