from __future__ import annotations

from talon.checks import dns_records
from talon.config import DnsDomain
from talon.models import Status

DOMAIN = DnsDomain("example.com")


def query_factory(table, errors=()):
    def query(name, rtype, resolver=None):
        key = (name, rtype, resolver or "authoritative")
        if key in errors:
            raise TimeoutError("no answer")
        return table.get(key, table.get((name, rtype), []))
    return query


def test_first_run_is_baseline(ctx):
    ctx.dns_query = query_factory({("example.com", "A"): ["1.2.3.4"], ("example.com", "TXT"): ['"v=spf1"']})
    results = dns_records.run(ctx, DOMAIN, ["example.com"])
    assert any(r.status is Status.INFO and "базовая линия" in r.summary_ru for r in results)
    assert ctx.state.read_json("example.com", "dns.json")["records"]["example.com"]["A"] == ["1.2.3.4"]


def test_a_record_change_fails(ctx):
    ctx.state.write_json("example.com", "dns.json", {
        "records": {"example.com": {"A": ["1.2.3.4"], "TXT": ['"v=spf1"']}}
    })
    ctx.dns_query = query_factory({("example.com", "A"): ["9.9.9.9"], ("example.com", "TXT"): ['"v=spf1"']})
    results = dns_records.run(ctx, DOMAIN, ["example.com"])
    changed = [r for r in results if r.changed]
    assert changed and changed[0].status is Status.FAIL
    assert "9.9.9.9" in changed[0].summary_ru


def test_txt_change_only_warns(ctx):
    ctx.state.write_json("example.com", "dns.json", {
        "records": {"example.com": {"A": ["1.2.3.4"], "TXT": ['"v=spf1"']}}
    })
    ctx.dns_query = query_factory({("example.com", "A"): ["1.2.3.4"], ("example.com", "TXT"): ['"other"']})
    results = dns_records.run(ctx, DOMAIN, ["example.com"])
    changed = [r for r in results if r.changed]
    assert changed and changed[0].status is Status.WARN


def test_expected_records_beat_state(ctx):
    domain = DnsDomain("example.com", expected={"A": ["1.2.3.4"]})
    ctx.dns_query = query_factory({("example.com", "A"): ["5.5.5.5"], ("example.com", "TXT"): []})
    results = dns_records.run(ctx, domain, ["example.com"])
    assert any(r.status is Status.FAIL and "не совпадают" in r.summary_ru for r in results)


def test_resolvers_disagreeing_warns(ctx):
    table = {
        ("example.com", "A", "1.1.1.1"): ["1.2.3.4"],
        ("example.com", "A", "authoritative"): ["9.9.9.9"],
        ("example.com", "TXT"): [],
    }
    ctx.dns_query = query_factory(table)
    results = dns_records.run(ctx, DOMAIN, ["example.com"])
    assert any(r.status is Status.WARN and "расходятся" in r.summary_ru for r in results)


def test_dead_resolver_does_not_break_the_run(ctx):
    ctx.dns_query = query_factory(
        {("example.com", "TXT"): []},
        errors={("example.com", "A", "1.1.1.1"), ("example.com", "A", "authoritative")},
    )
    results = dns_records.run(ctx, DOMAIN, ["example.com"])
    assert any(r.status is Status.WARN and "не выполнен" in r.summary_ru for r in results)


def test_rdap_unavailable_is_info(ctx):
    ctx.config.dns["rdap"] = True
    ctx.rdap_fetch = lambda domain: None
    ctx.dns_query = query_factory({("example.com", "A"): ["1.2.3.4"], ("example.com", "TXT"): []})
    results = dns_records.run(ctx, DOMAIN, ["example.com"])
    assert any(r.status is Status.INFO and "RDAP" in r.summary_ru for r in results)


def test_registrar_change_fails(ctx):
    ctx.config.dns["rdap"] = True
    ctx.state.write_json("example.com", "dns.json", {
        "records": {"example.com": {"A": ["1.2.3.4"], "TXT": []}},
        "rdap": {"registrar": "Old Registrar", "nameservers": ["ns1.example.com"], "expiry": None},
    })
    ctx.rdap_fetch = lambda domain: {"registrar": "New Registrar", "nameservers": ["ns1.example.com"],
                                     "expiry": None, "status": []}
    ctx.dns_query = query_factory({("example.com", "A"): ["1.2.3.4"], ("example.com", "TXT"): []})
    results = dns_records.run(ctx, DOMAIN, ["example.com"])
    assert any(r.status is Status.FAIL and "регистратор" in r.summary_ru for r in results)
