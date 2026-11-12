"""Find the chat id for the Telegram bot, and optionally send one test message.

Telegram's API needs a numeric chat id, not an @nickname (an @name works only for public
channels). So: create the bot with @BotFather, write TELEGRAM_BOT_TOKEN into .env, send the bot
any message from the chat or group you want the талон in, then run this.

    .venv/bin/python tools/chat_id.py              # list the chats the bot has seen
    .venv/bin/python tools/chat_id.py --test       # post a test message to TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from talon.__main__ import load_env  # noqa: E402
from talon.telegram import Telegram  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    load_env(ROOT / ".env")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set: put it in .env (see .env.example)", file=sys.stderr)
        return 1

    if "--test" in sys.argv:
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        if not chat:
            print("TELEGRAM_CHAT_ID is not set: run without --test first to find it", file=sys.stderr)
            return 1
        ok = Telegram(token=token, chat_id=chat).send(
            "🧾 <b>Талон</b> — тестовое сообщение.\nЕсли вы это видите, бот настроен правильно."
        )
        print("sent" if ok else "failed - see the error above")
        return 0 if ok else 1

    response = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20.0)
    if response.status_code != 200:
        print(f"Telegram answered HTTP {response.status_code}: {response.text[:300]}", file=sys.stderr)
        return 1
    updates = response.json().get("result") or []
    seen: dict[int, dict] = {}
    for update in updates:
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            seen[chat["id"]] = chat

    if not seen:
        print(
            "No chats yet. Send the bot any message (in a private chat, or add it to the group and\n"
            "write something there), then run this again. Groups: give the bot permission to post."
        )
        return 0

    print("Chats this bot can post to - put the id you want into .env as TELEGRAM_CHAT_ID:\n")
    for chat_id, chat in seen.items():
        name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
        username = f" @{chat['username']}" if chat.get("username") else ""
        print(f"  {chat_id:<16} {chat.get('type','?'):<10} {name}{username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
