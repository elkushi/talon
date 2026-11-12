from __future__ import annotations

import httpx
import respx

from talon.checks import pages
from talon.models import Status
from tests.conftest import make_site

HTML_OK = """<html><head><title>Главная</title>
<meta name="description" content="описание">
<link rel="canonical" href="https://www.example.com/"></head><body><p>текст</p></body></html>"""


@respx.mock
def test_meta_noindex_fails(ctx):
    body = HTML_OK.replace("<title>", '<meta name="robots" content="noindex, follow"><title>')
    respx.get("https://www.example.com/").mock(return_value=httpx.Response(200, text=body))
    results = pages.run(ctx, make_site())
    assert any(r.status is Status.FAIL and "noindex" in r.summary_ru for r in results)


@respx.mock
def test_x_robots_tag_noindex_fails(ctx):
    respx.get("https://www.example.com/").mock(
        return_value=httpx.Response(200, text=HTML_OK, headers={"X-Robots-Tag": "noindex"})
    )
    results = pages.run(ctx, make_site())
    assert any(r.status is Status.FAIL and "X-Robots-Tag" in r.summary_ru for r in results)


@respx.mock
def test_wrong_canonical_warns(ctx):
    body = HTML_OK.replace("https://www.example.com/", "https://other.example.net/")
    respx.get("https://www.example.com/").mock(return_value=httpx.Response(200, text=body))
    results = pages.run(ctx, make_site())
    assert any(r.status is Status.WARN and "canonical" in r.summary_ru for r in results)


@respx.mock
def test_clean_page_is_ok(ctx):
    respx.get("https://www.example.com/").mock(return_value=httpx.Response(200, text=HTML_OK))
    results = pages.run(ctx, make_site())
    assert [str(r.status) for r in results] == ["ok"]


@respx.mock
def test_non_200_fails(ctx):
    respx.get("https://www.example.com/").mock(return_value=httpx.Response(500))
    results = pages.run(ctx, make_site())
    assert results[0].status is Status.FAIL


def portal_site():
    return make_site(name="front.example.com", kind="portal", canonical="https://front.example.com",
                     variants=["http://front.example.com"], key_pages=["/auth"])


@respx.mock
def test_portal_over_plain_http_fails(ctx):
    login = ('<html><head><title>Вход</title><meta name="robots" content="noindex"></head>'
             '<body><form action="/auth"></form></body></html>')
    respx.get("https://front.example.com/auth").mock(return_value=httpx.Response(200, text=login))
    respx.get("http://front.example.com/auth").mock(return_value=httpx.Response(200, text=login))
    results = pages.run(ctx, portal_site())
    assert any(r.status is Status.FAIL and "по http" in r.summary_ru for r in results)


@respx.mock
def test_portal_form_posting_to_another_host_fails(ctx):
    login = ('<html><head><title>Вход</title><meta name="robots" content="noindex"></head>'
             '<body><form action="https://evil.example.org/collect"></form></body></html>')
    respx.get("https://front.example.com/auth").mock(return_value=httpx.Response(200, text=login))
    respx.get("http://front.example.com/auth").mock(
        return_value=httpx.Response(301, headers={"Location": "https://front.example.com/auth"})
    )
    results = pages.run(ctx, portal_site())
    assert any(r.status is Status.FAIL and "evil.example.org" in r.summary_ru for r in results)


@respx.mock
def test_indexable_login_page_warns(ctx):
    login = '<html><head><title>Вход</title></head><body><form action="/auth"></form></body></html>'
    respx.get("https://front.example.com/auth").mock(return_value=httpx.Response(200, text=login))
    respx.get("https://front.example.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("http://front.example.com/auth").mock(
        return_value=httpx.Response(301, headers={"Location": "https://front.example.com/auth"})
    )
    results = pages.run(ctx, portal_site())
    assert any(r.status is Status.WARN and "индексации" in r.summary_ru for r in results)
