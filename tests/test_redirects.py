from __future__ import annotations

import httpx
import respx

from talon.checks import redirects
from talon.models import Status
from tests.conftest import make_site, statuses

CANON = "https://www.example.com/"


def _canonical_ok(router):
    router.get(CANON).mock(return_value=httpx.Response(200, text="ok"))


@respx.mock
def test_single_permanent_hop_is_ok(ctx):
    _canonical_ok(respx)
    respx.get("http://example.com").mock(
        return_value=httpx.Response(301, headers={"Location": CANON})
    )
    results = redirects.run(ctx, make_site())
    assert statuses(results) == ["ok", "ok"]


@respx.mock
def test_temporary_redirect_warns(ctx):
    _canonical_ok(respx)
    respx.get("http://example.com").mock(return_value=httpx.Response(302, headers={"Location": CANON}))
    results = redirects.run(ctx, make_site())
    assert Status.WARN in [r.status for r in results]
    assert any("302" in r.summary_ru for r in results)


@respx.mock
def test_two_hops_warn(ctx):
    _canonical_ok(respx)
    respx.get("http://example.com").mock(
        return_value=httpx.Response(301, headers={"Location": "https://example.com/"})
    )
    respx.get("https://example.com/").mock(
        return_value=httpx.Response(301, headers={"Location": CANON})
    )
    results = redirects.run(ctx, make_site())
    assert any(r.status is Status.WARN and "перехода" in r.summary_ru for r in results)


@respx.mock
def test_http_200_without_https_fails(ctx):
    _canonical_ok(respx)
    respx.get("http://example.com").mock(return_value=httpx.Response(200, text="plain http"))
    results = redirects.run(ctx, make_site())
    assert any(r.status is Status.FAIL and "без перехода на https" in r.summary_ru for r in results)


@respx.mock
def test_loop_fails(ctx):
    _canonical_ok(respx)
    respx.get("http://example.com").mock(
        return_value=httpx.Response(301, headers={"Location": "http://example.com/"})
    )
    respx.get("http://example.com/").mock(
        return_value=httpx.Response(301, headers={"Location": "http://example.com"})
    )
    results = redirects.run(ctx, make_site())
    assert any(r.status is Status.FAIL and "петля" in r.summary_ru for r in results)


@respx.mock
def test_final_404_fails(ctx):
    _canonical_ok(respx)
    respx.get("http://example.com").mock(return_value=httpx.Response(301, headers={"Location": CANON + "gone"}))
    respx.get(CANON + "gone").mock(return_value=httpx.Response(404))
    results = redirects.run(ctx, make_site())
    assert any(r.status is Status.FAIL for r in results)


@respx.mock
def test_legacy_redirect_checked(ctx):
    _canonical_ok(respx)
    respx.get("http://example.com").mock(return_value=httpx.Response(301, headers={"Location": CANON}))
    respx.get(CANON + "old/").mock(return_value=httpx.Response(301, headers={"Location": CANON + "new/"}))
    respx.get(CANON + "new/").mock(return_value=httpx.Response(200, text="new"))
    site = make_site(legacy_redirects={"/old/": "/new/"})
    results = redirects.run(ctx, site)
    assert any("старый адрес" in r.summary_ru and r.status is Status.OK for r in results)


@respx.mock
def test_retry_once_after_503(ctx):
    respx.get(CANON).mock(side_effect=[httpx.Response(503), httpx.Response(200, text="ok")])
    respx.get("http://example.com").mock(return_value=httpx.Response(301, headers={"Location": CANON}))
    results = redirects.run(ctx, make_site())
    canonical = results[0]
    assert canonical.status is Status.OK
    assert canonical.details.get("note") == "повтор успешен"
