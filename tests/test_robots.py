from __future__ import annotations

import httpx
import respx

from talon.checks import robots
from talon.models import Status
from tests.conftest import make_site

URL = "https://www.example.com/robots.txt"
PLAIN = {"Content-Type": "text/plain"}
GOOD = "User-agent: *\nDisallow: /admin\nSitemap: https://www.example.com/sitemap.xml\n"


def _sitemap_ok():
    respx.head("https://www.example.com/sitemap.xml").mock(return_value=httpx.Response(200))


@respx.mock
def test_disallow_all_fails(ctx):
    respx.get(URL).mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /\n", headers=PLAIN))
    results = robots.run(ctx, make_site())
    assert any(r.status is Status.FAIL and "закрыт от индексации" in r.summary_ru for r in results)


@respx.mock
def test_key_page_blocked_for_yandex_fails(ctx):
    text = "User-agent: YandexBot\nDisallow: /prices\n\nUser-agent: *\nAllow: /\nSitemap: https://www.example.com/sitemap.xml\n"
    respx.get(URL).mock(return_value=httpx.Response(200, text=text, headers=PLAIN))
    _sitemap_ok()
    results = robots.run(ctx, make_site(key_pages=["/prices"]))
    assert any(r.status is Status.FAIL and "YandexBot" in r.summary_ru for r in results)


@respx.mock
def test_missing_sitemap_line_warns(ctx):
    respx.get(URL).mock(return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n", headers=PLAIN))
    results = robots.run(ctx, make_site())
    assert any(r.status is Status.WARN and "Sitemap" in r.summary_ru for r in results)


@respx.mock
def test_change_produces_diff(ctx):
    ctx.state.write_text("example.com", "robots.txt", GOOD)
    changed = GOOD.replace("/admin", "/admin\nDisallow: /blog")
    respx.get(URL).mock(return_value=httpx.Response(200, text=changed, headers=PLAIN))
    _sitemap_ok()
    results = robots.run(ctx, make_site())
    diffs = [r for r in results if r.changed]
    assert diffs and diffs[0].status is Status.WARN
    assert any("/blog" in line for line in diffs[0].details["diff"])


@respx.mock
def test_ai_bot_newly_blocked_warns(ctx):
    ctx.state.write_text("example.com", "robots.txt", GOOD)
    changed = "User-agent: GPTBot\nDisallow: /\n\n" + GOOD
    respx.get(URL).mock(return_value=httpx.Response(200, text=changed, headers=PLAIN))
    _sitemap_ok()
    results = robots.run(ctx, make_site())
    assert any("GPTBot" in r.summary_ru for r in results)


@respx.mock
def test_first_run_saves_baseline(ctx):
    respx.get(URL).mock(return_value=httpx.Response(200, text=GOOD, headers=PLAIN))
    _sitemap_ok()
    results = robots.run(ctx, make_site())
    assert any(r.status is Status.INFO for r in results)
    assert ctx.state.read_text("example.com", "robots.txt") == GOOD


@respx.mock
def test_failed_fetch_does_not_overwrite_baseline(ctx):
    ctx.state.write_text("example.com", "robots.txt", GOOD)
    respx.get(URL).mock(return_value=httpx.Response(503))
    results = robots.run(ctx, make_site())
    assert results[0].status is Status.FAIL
    assert ctx.state.read_text("example.com", "robots.txt") == GOOD
