"""What every check gets: config, the fetcher, state, and injectable network probes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .config import Config
from .http import Fetcher
from .state import State


@dataclass
class Context:
    config: Config
    fetcher: Fetcher
    state: State
    now: datetime
    # injected so tests never touch the network
    ssl_probe: Callable[[str, int], dict] | None = None
    dns_query: Callable[[str, str, str | None], list[str]] | None = None
    rdap_fetch: Callable[[str], dict | None] | None = None
    save_state: bool = True
    extra: dict = field(default_factory=dict)
