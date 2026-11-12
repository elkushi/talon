"""CLI: python -m talon --mode daily|watch [--dry-run] [--accept domain/check]."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import messages as M
from . import report, runner
from .config import ConfigError, load
from .context import Context
from .http import Fetcher, build_client
from .state import State
from .telegram import Telegram, TelegramError

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"


def load_env(path: Path) -> None:
    """Minimal .env reader, so the tool has no extra dependency for one file."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def setup_logging(level: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "talon.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler(sys.stderr)],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="talon", description="Talon - site & domain monitor")
    parser.add_argument("--mode", choices=["daily", "watch"], default="daily")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="print the талон instead of sending it")
    parser.add_argument("--accept", metavar="DOMAIN/CHECK", help="accept the current state as the new baseline")
    parser.add_argument("--state", default=str(ROOT / "state"))
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def build_context(args, config, now) -> Context:
    client = build_client()
    return Context(
        config=config,
        fetcher=Fetcher(client, retry_after=config.retry_after_seconds),
        state=State(args.state),
        now=now,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    log = logging.getLogger("talon")
    load_env(ROOT / ".env")

    try:
        config = load(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    todos = config.todos() if not args.accept else []
    if todos:
        message = "config still has TODO placeholders:\n  " + "\n  ".join(todos)
        if args.dry_run:
            print(f"warning: {message}\n", file=sys.stderr)
        else:
            print(f"error: {message}\nfill them in, or run with --dry-run", file=sys.stderr)
            return 1

    now = datetime.now(ZoneInfo(config.timezone))
    ctx = build_context(args, config, now)

    if args.accept:
        try:
            removed = runner.accept(ctx, args.accept)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if removed:
            print("baseline reset:\n  " + "\n  ".join(removed))
        else:
            print(f"nothing stored for {args.accept} - the next run will save a baseline")
        return 0

    telegram = Telegram.from_env(
        config.telegram.get("token_env", "TELEGRAM_BOT_TOKEN"),
        config.telegram.get("chat_id_env", "TELEGRAM_CHAT_ID"),
    )

    try:
        results = runner.run(ctx, args.mode)
        messages = (
            report.daily(config, results, now, domains=len(config.dns_domains))
            if args.mode == "daily"
            else report.watch(config, results, now)
        )

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"report-{now:%Y-%m-%d}-{args.mode}.json"
        log_path.write_text(
            json.dumps(
                {
                    "mode": args.mode,
                    "at": now.isoformat(timespec="seconds"),
                    "summary": runner.summary(results),
                    "results": [r.as_dict() for r in results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        state = State(args.state)
        last = state.read_last_run()
        last[args.mode] = {"at": now.isoformat(timespec="seconds"), **runner.summary(results)}
        state.write_last_run(last)

        if not messages:
            log.info("%s: nothing to report", args.mode)
            return 0
        if args.dry_run:
            print(("\n" + "-" * 40 + "\n").join(messages))
            return 0
        if not telegram.configured:
            print("error: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set (see .env.example)", file=sys.stderr)
            return 1
        telegram.send_all(messages)
        return 0
    except Exception as exc:  # noqa: BLE001 - report the failure, then exit 1
        log.exception("run failed")
        reason = f"{type(exc).__name__}: {exc}"[:300]
        if not args.dry_run and telegram.configured:
            try:
                telegram.send(M.RUN_FAILED.format(reason=report.esc(reason)))
            except TelegramError:
                pass
        print(f"run failed: {reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
