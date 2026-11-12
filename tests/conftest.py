from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from talon.config import Config, DnsDomain, Site
from talon.context import Context
from talon.http import Fetcher
from talon.state import State

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))


def make_site(**kw) -> Site:
    data = {
        "name": "example.com",
        "kind": "marketing",
        "canonical": "https://www.example.com",
        "variants": ["http://example.com"],
        "key_pages": ["/"],
        "legacy_redirects": {},
        "sitemaps": [],
    }
    data.update(kw)
    return Site(**data)


def make_config(sites=None, **kw) -> Config:
    data = {
        "sites": sites or [make_site()],
        "dns_domains": [DnsDomain("example.com")],
        "bots": {"search": ["Googlebot", "YandexBot"], "ai": ["GPTBot"]},
        "http": {"retry_once_after_seconds": 0},
        "sitemap": {"max_urls": 500},
        "ssl": {"warn_days": 21, "fail_days": 7, "allowed_issuers": []},
        "dns": {"resolvers": ["1.1.1.1"], "record_types": ["A", "TXT"], "rdap": False},
        "content": {"ignore_patterns": [], "allowed_external_domains": []},
        "telegram": {},
    }
    data.update(kw)
    return Config(**data)


@pytest.fixture
def ctx(tmp_path):
    client = httpx.Client(follow_redirects=False, timeout=5.0)
    return Context(
        config=make_config(),
        fetcher=Fetcher(client, retry_after=0, sleep=lambda _: None),
        state=State(tmp_path / "state"),
        now=NOW,
    )


def statuses(results):
    return [str(r.status) for r in results]


def summaries(results):
    return [r.summary_ru for r in results]
