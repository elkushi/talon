"""The only place that talks HTTP to the monitored sites. GET/HEAD only, never POST."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

USER_AGENT = "Talon/1.0 (+https://github.com/elkushi/talon)"
TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)
PERMANENT = {301, 308}
TEMPORARY = {302, 303, 307}
MAX_HOPS = 10

log = logging.getLogger(__name__)


def build_client(**kwargs) -> httpx.Client:
    """Shared client: no automatic redirects (we walk them ourselves), one connection per host."""
    limits = httpx.Limits(max_connections=5, max_keepalive_connections=5)
    return httpx.Client(
        follow_redirects=False,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        limits=limits,
        verify=True,
        **kwargs,
    )


def is_tls_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".upper()
    return any(word in text for word in ("SSL", "CERTIFICATE", "TLS", "HANDSHAKE"))


def describe(exc: Exception) -> str:
    msg = str(exc).strip() or type(exc).__name__
    return f"{type(exc).__name__}: {msg}"[:200]


@dataclass
class Hop:
    url: str
    status: int | None = None
    location: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {"url": self.url, "status": self.status, "location": self.location, "error": self.error}


@dataclass
class Chain:
    start: str
    hops: list[Hop] = field(default_factory=list)
    final_url: str | None = None
    final_status: int | None = None
    error: str | None = None
    tls_error: bool = False
    loop: bool = False
    retried: bool = False
    elapsed: float = 0.0

    @property
    def permanent_hops(self) -> int:
        return sum(1 for h in self.hops if h.status in PERMANENT)

    @property
    def redirect_hops(self) -> int:
        return sum(1 for h in self.hops if h.status and 300 <= h.status < 400)

    @property
    def temporary_used(self) -> bool:
        return any(h.status in TEMPORARY for h in self.hops)

    def as_dict(self) -> dict:
        return {
            "start": self.start,
            "hops": [h.as_dict() for h in self.hops],
            "final_url": self.final_url,
            "final_status": self.final_status,
            "error": self.error,
            "tls_error": self.tls_error,
            "loop": self.loop,
            "retried": self.retried,
            "elapsed_s": round(self.elapsed, 3),
        }


@dataclass
class Fetch:
    """One request's outcome. `response` is None when the request failed."""

    url: str
    response: httpx.Response | None = None
    error: str | None = None
    tls_error: bool = False
    retried: bool = False
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.response is not None

    @property
    def status(self) -> int | None:
        return self.response.status_code if self.response is not None else None

    @property
    def text(self) -> str:
        return self.response.text if self.response is not None else ""


class Fetcher:
    """Wraps the client with the retry rule: one retry after 5 s on a failure or 5xx."""

    def __init__(
        self,
        client: httpx.Client,
        retry_after: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.retry_after = retry_after
        self.sleep = sleep

    def request(self, url: str, method: str = "GET") -> Fetch:
        if method.upper() not in {"GET", "HEAD"}:  # hard rule: read-only
            raise ValueError(f"method {method} is not allowed - Talon is read-only")
        started = time.monotonic()
        result = self._once(url, method)
        if result.response is None or (result.response.status_code >= 500):
            log.info("retrying %s in %.0fs (%s)", url, self.retry_after, result.error or result.status)
            self.sleep(self.retry_after)
            retry = self._once(url, method)
            retry.retried = True
            retry.elapsed = time.monotonic() - started
            if retry.response is not None:
                return retry
            # retry blew up too: keep whichever attempt actually produced a response
            if result.response is not None:
                result.retried = True
                result.elapsed = time.monotonic() - started
                return result
            return retry
        result.elapsed = time.monotonic() - started
        return result

    def _once(self, url: str, method: str) -> Fetch:
        try:
            response = self.client.request(method, url)
            return Fetch(url=url, response=response)
        except Exception as exc:  # noqa: BLE001 - a crash here must not kill the run
            return Fetch(url=url, error=describe(exc), tls_error=is_tls_error(exc))

    # --- redirects ---------------------------------------------------------
    def walk(self, url: str, max_hops: int = MAX_HOPS) -> Chain:
        """Follow redirects by hand so every hop and its status are recorded."""
        chain = Chain(start=url)
        started = time.monotonic()
        seen: set[str] = set()
        current = url
        for _ in range(max_hops + 1):
            if current in seen:
                chain.loop = True
                chain.final_url = current
                break
            seen.add(current)
            fetch = self.request(current, method="GET")
            chain.retried = chain.retried or fetch.retried
            if fetch.response is None:
                chain.hops.append(Hop(url=current, error=fetch.error))
                chain.error = fetch.error
                chain.tls_error = fetch.tls_error
                chain.final_url = current
                break
            status = fetch.response.status_code
            location = fetch.response.headers.get("location")
            chain.hops.append(Hop(url=current, status=status, location=location))
            if 300 <= status < 400 and location:
                current = str(httpx.URL(current).join(location))
                continue
            chain.final_url = current
            chain.final_status = status
            break
        else:
            chain.loop = True
            chain.final_url = current
        chain.elapsed = time.monotonic() - started
        return chain
