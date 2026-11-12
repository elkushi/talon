"""Posting the талон. The only outbound write in the whole tool."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

import httpx

API = "https://api.telegram.org/bot{token}/sendMessage"
RETRIES = 3

log = logging.getLogger(__name__)


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.client = client or httpx.Client(timeout=20.0)
        self.sleep = sleep

    @classmethod
    def from_env(cls, token_env: str = "TELEGRAM_BOT_TOKEN", chat_env: str = "TELEGRAM_CHAT_ID", **kw):
        return cls(token=os.environ.get(token_env), chat_id=os.environ.get(chat_env), **kw)

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.configured:
            raise TelegramError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set")
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        delay = 2.0
        last = ""
        for attempt in range(1, RETRIES + 1):
            try:
                response = self.client.post(API.format(token=self.token), json=payload)
                if response.status_code == 200:
                    return True
                last = f"HTTP {response.status_code}: {response.text[:200]}"
            except Exception as exc:  # noqa: BLE001
                last = f"{type(exc).__name__}: {exc}"[:200]
            log.warning("telegram send failed (attempt %s/%s): %s", attempt, RETRIES, last)
            if attempt < RETRIES:
                self.sleep(delay)
                delay *= 2
        log.error("telegram send gave up: %s", last)
        return False

    def send_all(self, messages: list[str]) -> bool:
        return all([self.send(m) for m in messages])
