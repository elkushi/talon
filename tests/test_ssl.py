from __future__ import annotations

from talon.checks import ssl_cert
from talon.models import Status
from tests.conftest import make_site

HOSTS = make_site(variants=["http://example.com"])  # hosts: www.example.com, example.com


def probe_factory(**per_host):
    def probe(host, port=443):
        return per_host.get(host, {"verified": True, "issuer": "Let's Encrypt",
                                   "not_after": "Dec 25 12:00:00 2026 GMT", "sans": [host], "error": None})
    return probe


def test_expiring_soon_fails(ctx):
    ctx.ssl_probe = probe_factory(**{
        "www.example.com": {"verified": True, "issuer": "Let's Encrypt",
                            "not_after": "Nov 17 12:00:00 2026 GMT", "sans": ["www.example.com"], "error": None}
    })
    results = ssl_cert.run(ctx, HOSTS)
    assert any(r.status is Status.FAIL and "5 дней" in r.summary_ru for r in results)


def test_warn_window(ctx):
    ctx.ssl_probe = probe_factory(**{
        "www.example.com": {"verified": True, "issuer": "Let's Encrypt",
                            "not_after": "Nov 27 12:00:00 2026 GMT", "sans": ["www.example.com"], "error": None}
    })
    results = ssl_cert.run(ctx, HOSTS)
    assert any(r.status is Status.WARN for r in results)


def test_issuer_change_fails(ctx):
    ctx.state.write_json("example.com", "ssl.json", {
        "www.example.com": {"issuer": "Let's Encrypt", "not_after": "Dec 25 12:00:00 2026 GMT"},
        "example.com": {"issuer": "Let's Encrypt", "not_after": "Dec 25 12:00:00 2026 GMT"},
    })
    ctx.ssl_probe = probe_factory(**{
        "www.example.com": {"verified": True, "issuer": "Unknown CA",
                            "not_after": "Dec 25 12:00:00 2026 GMT", "sans": ["www.example.com"], "error": None}
    })
    results = ssl_cert.run(ctx, HOSTS)
    assert any(r.status is Status.FAIL and r.changed and "издатель" in r.summary_ru for r in results)


def test_hostname_not_covered_fails(ctx):
    ctx.ssl_probe = probe_factory(**{
        "example.com": {"verified": False, "issuer": "Let's Encrypt",
                        "not_after": "Dec 25 12:00:00 2026 GMT", "sans": ["www.example.com"],
                        "error": "SSLCertVerificationError: hostname mismatch"}
    })
    results = ssl_cert.run(ctx, HOSTS)
    assert any(r.status is Status.FAIL and "не покрывает example.com" in r.summary_ru for r in results)


def test_first_run_is_baseline(ctx):
    ctx.ssl_probe = probe_factory()
    results = ssl_cert.run(ctx, HOSTS)
    assert any(r.status is Status.INFO for r in results)
    assert ctx.state.read_json("example.com", "ssl.json")["www.example.com"]["issuer"] == "Let's Encrypt"


def test_unreadable_certificate_is_retried_once(ctx):
    attempts = []

    def flaky(host, port=443):
        attempts.append(host)
        if len(attempts) == 1:
            return {"verified": False, "issuer": None, "not_after": None, "sans": [],
                    "error": "TimeoutError: timed out"}
        return {"verified": True, "issuer": "Let's Encrypt", "not_after": "Dec 25 12:00:00 2026 GMT",
                "sans": [host], "error": None}

    ctx.ssl_probe = flaky
    results = ssl_cert.run(ctx, make_site(variants=[]))
    assert len(attempts) == 2
    assert not [r for r in results if r.status is Status.FAIL]


def test_unreachable_host_is_not_called_a_bad_certificate(ctx):
    ctx.ssl_probe = lambda host, port=443: {"verified": False, "issuer": None, "not_after": None,
                                            "sans": [], "error": "TimeoutError: handshake timed out"}
    results = ssl_cert.run(ctx, make_site(variants=[]))
    assert results[0].status is Status.FAIL
    assert "не ответил по https" in results[0].summary_ru
