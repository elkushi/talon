from __future__ import annotations

import httpx
import respx

from talon.checks import sitemap
from talon.models import Status
from tests.conftest import make_site

XML_HEADERS = {"Content-Type": "application/xml"}
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(urls):
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset {NS}>{body}</urlset>'


def index(maps):
    body = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in maps)
    return f'<?xml version="1.0"?><sitemapindex {NS}>{body}</sitemapindex>'


def _site():
    return make_site(sitemaps=["https://www.example.com/sitemap.xml"])


@respx.mock
def test_index_file_is_followed(ctx):
    respx.get("https://www.example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text=index(["https://www.example.com/s1.xml"]), headers=XML_HEADERS)
    )
    respx.get("https://www.example.com/s1.xml").mock(
        return_value=httpx.Response(200, text=urlset(["https://www.example.com/a"]), headers=XML_HEADERS)
    )
    respx.head("https://www.example.com/a").mock(return_value=httpx.Response(200))
    results = sitemap.run(ctx, _site())
    assert any(r.status is Status.INFO for r in results)  # baseline saved
    assert not [r for r in results if r.status is Status.FAIL]


@respx.mock
def test_redirecting_url_warns(ctx):
    respx.get("https://www.example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text=urlset([f"https://www.example.com/p{i}" for i in range(20)]),
                                    headers=XML_HEADERS)
    )
    for i in range(20):
        code = 301 if i == 0 else 200
        respx.head(f"https://www.example.com/p{i}").mock(return_value=httpx.Response(code))
    results = sitemap.run(ctx, _site())
    bad = [r for r in results if "URL отвечают не 200" in r.summary_ru]
    assert bad and bad[0].status is Status.WARN


@respx.mock
def test_more_than_ten_percent_failing_fails(ctx):
    respx.get("https://www.example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text=urlset([f"https://www.example.com/p{i}" for i in range(10)]),
                                    headers=XML_HEADERS)
    )
    for i in range(10):
        respx.head(f"https://www.example.com/p{i}").mock(return_value=httpx.Response(404 if i < 3 else 200))
    results = sitemap.run(ctx, _site())
    assert any(r.status is Status.FAIL for r in results)


@respx.mock
def test_count_drop_warns(ctx):
    ctx.state.write_json("example.com", "sitemap.json", {"url_count": 10})
    respx.get("https://www.example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text=urlset(["https://www.example.com/a"]), headers=XML_HEADERS)
    )
    respx.head("https://www.example.com/a").mock(return_value=httpx.Response(200))
    results = sitemap.run(ctx, _site())
    assert any(r.changed and "число URL" in r.summary_ru for r in results)


@respx.mock
def test_broken_xml_fails(ctx):
    respx.get("https://www.example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text="<urlset><loc>oops", headers=XML_HEADERS)
    )
    results = sitemap.run(ctx, _site())
    assert any(r.status is Status.FAIL for r in results)


@respx.mock
def test_redirecting_sitemap_is_followed_and_warned(ctx):
    respx.get("https://www.example.com/sitemap.xml").mock(
        return_value=httpx.Response(301, headers={"Location": "https://www.example.com/sitemap-1.xml"})
    )
    respx.get("https://www.example.com/sitemap-1.xml").mock(
        return_value=httpx.Response(200, text=urlset(["https://www.example.com/a"]), headers=XML_HEADERS)
    )
    respx.head("https://www.example.com/a").mock(return_value=httpx.Response(200))
    results = sitemap.run(ctx, _site())
    assert any(r.status is Status.WARN and "ведёт на" in r.summary_ru for r in results)
    assert not [r for r in results if r.status is Status.FAIL]
    assert ctx.state.read_json("example.com", "sitemap.json")["url_count"] == 1
