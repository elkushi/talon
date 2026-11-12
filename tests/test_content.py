from __future__ import annotations

import httpx
import respx

from talon.checks import content
from talon.models import Status
from tests.conftest import make_site

URL = "https://www.example.com/"
PAGE = """<html><head><title>Example Shop</title><link rel="canonical" href="https://www.example.com/"></head>
<body><header><a href="/about">О нас</a></header><p>Мы отправляем SMS. Обновлено 12.11.2026</p>
<script src="https://mc.yandex.ru/metrika/tag.js"></script></body></html>"""


def _baseline(ctx, body=PAGE):
    respx.get(URL).mock(return_value=httpx.Response(200, text=body))
    content.run(ctx, make_site())


@respx.mock
def test_first_run_saves_baseline(ctx):
    _baseline(ctx)
    meta = ctx.state.read_json("example.com", "content/root.json")
    assert meta["title"] == "Example Shop"
    assert meta["external_domains"] == ["mc.yandex.ru"]


@respx.mock
def test_text_change_produces_diff(ctx):
    _baseline(ctx)
    changed = PAGE.replace("Мы отправляем SMS.", "Мы отправляем SMS и звоним.")
    respx.get(URL).mock(return_value=httpx.Response(200, text=changed))
    results = content.run(ctx, make_site())
    diff = [r for r in results if r.changed and "текст" in r.summary_ru]
    assert diff and diff[0].status is Status.WARN
    assert diff[0].details["diff"]


@respx.mock
def test_new_external_script_fails(ctx):
    _baseline(ctx)
    changed = PAGE.replace("</body>", '<script src="https://evil.example.org/x.js"></script></body>')
    respx.get(URL).mock(return_value=httpx.Response(200, text=changed))
    results = content.run(ctx, make_site())
    assert any(r.status is Status.FAIL and "evil.example.org" in r.summary_ru for r in results)


@respx.mock
def test_allowed_external_domain_is_quiet(ctx):
    ctx.config.content["allowed_external_domains"] = ["cdn.example.net"]
    _baseline(ctx)
    changed = PAGE.replace("</body>", '<script src="https://cdn.example.net/x.js"></script></body>')
    respx.get(URL).mock(return_value=httpx.Response(200, text=changed))
    results = content.run(ctx, make_site())
    assert not [r for r in results if r.status is Status.FAIL]


@respx.mock
def test_ignore_patterns_keep_the_hash_stable(ctx):
    ctx.config.content["ignore_patterns"] = [r"Обновлено \d{2}\.\d{2}\.\d{4}"]
    _baseline(ctx)
    changed = PAGE.replace("12.11.2026", "13.11.2026")
    respx.get(URL).mock(return_value=httpx.Response(200, text=changed))
    results = content.run(ctx, make_site())
    assert not [r for r in results if r.changed]


@respx.mock
def test_title_change_warns(ctx):
    _baseline(ctx)
    changed = PAGE.replace("<title>Example Shop</title>", "<title>Взломано</title>")
    respx.get(URL).mock(return_value=httpx.Response(200, text=changed))
    results = content.run(ctx, make_site())
    assert any("title" in r.summary_ru for r in results)
