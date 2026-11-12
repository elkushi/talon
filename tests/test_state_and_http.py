from __future__ import annotations

import httpx
import pytest
import respx

from talon import runner
from talon.http import Fetcher
from talon.state import State


def test_accept_resets_one_check(tmp_path):
    state = State(tmp_path)
    state.write_json("example.org", "dns.json", {"records": {"a": 1}})
    state.write_text("example.org", "robots.txt", "User-agent: *")
    removed = state.accept("example.org", "dns")
    assert removed
    assert state.read_json("example.org", "dns.json") is None
    assert state.read_text("example.org", "robots.txt") == "User-agent: *"


def test_accept_rejects_unknown_check(tmp_path):
    with pytest.raises(ValueError):
        State(tmp_path).accept("example.com", "nonsense")


def test_accept_spec_needs_a_slash(ctx):
    with pytest.raises(ValueError):
        runner.accept(ctx, "example.com")


def test_writes_are_atomic_and_leave_no_temp_files(tmp_path):
    state = State(tmp_path)
    state.write_text("a.com", "robots.txt", "x")
    assert not list((tmp_path / "a.com").glob("*.tmp"))


@respx.mock
def test_retry_waits_the_configured_time():
    waited = []
    client = httpx.Client(follow_redirects=False)
    fetcher = Fetcher(client, retry_after=5, sleep=waited.append)
    respx.get("https://a.example/").mock(side_effect=[httpx.Response(503), httpx.Response(200)])
    fetch = fetcher.request("https://a.example/")
    assert fetch.status == 200
    assert fetch.retried is True
    assert waited == [5]


@respx.mock
def test_post_is_refused():
    fetcher = Fetcher(httpx.Client(), retry_after=0, sleep=lambda _: None)
    with pytest.raises(ValueError):
        fetcher.request("https://a.example/", method="POST")


@respx.mock
def test_crashing_check_becomes_a_fail_result(ctx):
    def boom(_ctx, _site):
        raise RuntimeError("boom")

    results = runner._safe("redirects", "example.com", boom, ctx, None)
    assert results[0].status.value == "fail"
    assert "RuntimeError" in results[0].summary_ru
