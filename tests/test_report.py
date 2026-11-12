from __future__ import annotations

from talon import report
from talon.models import CheckResult, Status
from tests.conftest import NOW, make_config, make_site


def cfg(**kw):
    sites = [make_site(name=f"site{i}.com") for i in range(3)]
    return make_config(sites=sites, **kw)


def test_ok_sites_are_folded_into_one_line():
    results = [
        CheckResult("redirects", "site0.com", Status.OK, "Redirects: ок"),
        CheckResult("redirects", "site1.com", Status.OK, "Redirects: ок"),
        CheckResult("redirects", "site2.com", Status.FAIL, "Redirects: сломано"),
    ]
    text = "\n".join(report.daily(cfg(), results, NOW))
    assert "Без замечаний (2)" in text
    assert "site2.com" in text
    assert "Итог: 2 ✅ · 0 ⚠️ · 1 ❌" in text


def test_fail_block_comes_before_warn_block():
    results = [
        CheckResult("headers", "site0.com", Status.WARN, "Headers: нет HSTS"),
        CheckResult("redirects", "site1.com", Status.FAIL, "Redirects: сломано"),
    ]
    text = "\n".join(report.daily(cfg(), results, NOW))
    assert text.index("site1.com") < text.index("site0.com")


def test_html_is_escaped():
    results = [CheckResult("content", "site0.com", Status.FAIL, 'Content: <script>alert("x")</script>')]
    text = "\n".join(report.daily(cfg(), results, NOW))
    assert "&lt;script&gt;" in text
    assert "<script>" not in text


def test_mention_added_only_on_fail():
    config = cfg(telegram={"mention_on_fail": ["@gleb"]})
    warn_only = [CheckResult("headers", "site0.com", Status.WARN, "Headers: нет HSTS")]
    assert "@gleb" not in "\n".join(report.daily(config, warn_only, NOW))
    failing = [CheckResult("redirects", "site0.com", Status.FAIL, "Redirects: сломано")]
    assert "@gleb" in "\n".join(report.daily(config, failing, NOW))


def test_long_report_is_split_at_domain_boundaries():
    results = []
    for i in range(80):
        results.append(CheckResult("content", f"site{i}.com", Status.FAIL, "Content: " + "очень длинная строка " * 5))
    messages = report.daily(cfg(), results, NOW)
    assert len(messages) > 1
    assert all(len(m) <= 4096 for m in messages)
    assert all(not m.startswith("\n") for m in messages)


def test_watch_sends_nothing_when_quiet():
    results = [CheckResult("dns", "site0.com", Status.OK, "DNS: без изменений")]
    assert report.watch(cfg(), results, NOW) == []


def test_watch_alerts_on_change():
    results = [CheckResult("dns", "site0.com", Status.FAIL, "DNS: A изменились", changed=True)]
    text = "\n".join(report.watch(cfg(), results, NOW))
    assert "🚨" in text and "site0.com" in text
