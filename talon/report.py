"""Builds the талон: a short Russian HTML message for Telegram."""

from __future__ import annotations

import html
from collections import OrderedDict
from datetime import datetime

from .config import Config
from .models import SEVERITY, CheckResult, Status, worst

LIMIT = 4096
TZ_LABEL = {"Europe/Moscow": "MSK"}


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


def group(results: list[CheckResult]) -> OrderedDict[str, list[CheckResult]]:
    grouped: OrderedDict[str, list[CheckResult]] = OrderedDict()
    for r in results:
        grouped.setdefault(r.domain, []).append(r)
    return grouped


def _header(config: Config, now: datetime, sites: int, domains: int) -> str:
    label = TZ_LABEL.get(config.timezone, config.timezone)
    return (
        f"🧾 <b>Талон</b> — {sites} сайтов · {domains} доменов\n"
        f"{now.strftime('%d.%m.%Y')} · {now.strftime('%H:%M')} {label}"
    )


def _lines(results: list[CheckResult]) -> list[str]:
    ordered = sorted(results, key=lambda r: (SEVERITY[r.status], r.check))
    return [f"{r.icon} {esc(r.summary_ru)}" for r in ordered if r.status is not Status.OK]


def _counts(grouped: dict[str, list[CheckResult]]) -> tuple[int, int, int]:
    ok = warn = fail = 0
    for results in grouped.values():
        status = worst(results)
        if status is Status.FAIL:
            fail += 1
        elif status is Status.WARN:
            warn += 1
        else:
            ok += 1
    return ok, warn, fail


def split(blocks: list[str], header: str, footer: str, limit: int = LIMIT) -> list[str]:
    """Pack blocks into messages that fit Telegram's limit, never cutting a block in half."""
    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) + len(footer) + 2 > limit and current not in ("", header):
            messages.append(current)
            current = block
        elif len(candidate) + len(footer) + 2 > limit and current == header:
            messages.append(current)
            current = block
        else:
            current = candidate
    if footer:
        if len(current) + len(footer) + 2 > limit:
            messages.append(current)
            current = footer
        else:
            current = f"{current}\n\n{footer}" if current else footer
    if current:
        messages.append(current)
    return messages


def daily(config: Config, results: list[CheckResult], now: datetime, domains: int | None = None) -> list[str]:
    grouped = group(results)
    ok, warn, fail = _counts(grouped)
    sites = len(config.sites)
    domain_count = domains if domains is not None else len(config.dns_domains)

    problem_blocks: list[str] = []
    clean: list[str] = []
    for name, items in sorted(grouped.items(), key=lambda kv: (SEVERITY[worst(kv[1])], kv[0])):
        lines = _lines(items)
        if lines:
            problem_blocks.append("<b>" + esc(name) + "</b>\n" + "\n".join(lines))
        else:
            clean.append(name)

    if clean:
        problem_blocks.append(f"✅ Без замечаний ({len(clean)}): " + esc(", ".join(sorted(clean))))

    footer = f"Итог: {ok} ✅ · {warn} ⚠️ · {fail} ❌"
    if fail and config.mention_on_fail:
        footer += "\n" + esc(" ".join(config.mention_on_fail))
    return split(problem_blocks, _header(config, now, sites, domain_count), footer)


def watch(config: Config, results: list[CheckResult], now: datetime) -> list[str]:
    """Only changed or failing items, one alert per domain. Empty list = nothing to send."""
    notable = [r for r in results if r.changed or r.status is Status.FAIL]
    if not notable:
        return []
    blocks: list[str] = []
    for name, items in group(notable).items():
        lines = _lines(items) or [f"{r.icon} {esc(r.summary_ru)}" for r in items]
        blocks.append(f"🚨 <b>Изменение — {esc(name)}</b>\n" + "\n".join(lines))
    header = f"{now.strftime('%d.%m.%Y %H:%M')} {TZ_LABEL.get(config.timezone, config.timezone)}"
    footer = esc(" ".join(config.mention_on_fail)) if config.mention_on_fail else ""
    return split(blocks, header, footer)
