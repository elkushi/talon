"""5.2 robots: the file must not block the pages that have to rank."""

from __future__ import annotations

import difflib

from protego import Protego

from .. import messages as M
from ..config import Site
from ..context import Context
from ..models import CheckResult, Status

STATE_FILE = "robots.txt"
MAX_DIFF_LINES = 20


def _diff(old: str, new: str) -> list[str]:
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), fromfile="robots.txt (было)", tofile="robots.txt (стало)",
        lineterm="", n=1,
    )
    return list(lines)[:MAX_DIFF_LINES]


def _blocks_whole_site(text: str) -> bool:
    """True if the `User-agent: *` group contains a bare `Disallow: /`."""
    in_star = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            in_star = value == "*"
        elif key == "disallow" and in_star and value == "/":
            return True
    return False


def run(ctx: Context, site: Site) -> list[CheckResult]:
    url = site.canonical + "/robots.txt"
    fetch = ctx.fetcher.request(url)
    out: list[CheckResult] = []

    if fetch.response is None:
        return [
            CheckResult("robots", site.name, Status.FAIL, M.RB_DOWN.format(problem=fetch.error),
                        {"url": url, "error": fetch.error})
        ]
    status = fetch.response.status_code
    if status >= 500:
        return [
            CheckResult("robots", site.name, Status.FAIL, M.RB_DOWN.format(problem=f"код {status}"),
                        {"url": url, "status": status})
        ]
    if status == 404:
        return [CheckResult("robots", site.name, Status.WARN, M.RB_404, {"url": url, "status": status})]
    if status != 200:
        return [
            CheckResult("robots", site.name, Status.WARN, M.RB_DOWN.format(problem=f"код {status}"),
                        {"url": url, "status": status})
        ]

    ctype = fetch.response.headers.get("content-type", "")
    if "text/plain" not in ctype:
        out.append(CheckResult("robots", site.name, Status.WARN, M.RB_TYPE.format(ctype=ctype or "—"),
                               {"content_type": ctype}))

    text = fetch.response.text
    parsed = Protego.parse(text)

    if _blocks_whole_site(text):
        out.append(CheckResult("robots", site.name, Status.FAIL, M.RB_DISALLOW_ALL, {"url": url}))

    for bot in ctx.config.search_bots:
        for path in site.key_pages:
            if not parsed.can_fetch(site.url(path), bot):
                out.append(
                    CheckResult("robots", site.name, Status.FAIL,
                                M.RB_PAGE_BLOCKED.format(bot=bot, path=path), {"bot": bot, "path": path})
                )

    previous = ctx.state.read_text(site.name, STATE_FILE)
    if previous is not None and ctx.config.ai_bots:
        before = Protego.parse(previous)
        for bot in ctx.config.ai_bots:
            for path in site.key_pages:
                was = before.can_fetch(site.url(path), bot)
                now = parsed.can_fetch(site.url(path), bot)
                if was and not now:
                    out.append(
                        CheckResult("robots", site.name, Status.WARN,
                                    M.RB_AI_BLOCKED.format(bot=bot, path=path), {"bot": bot, "path": path})
                    )

    sitemaps = list(parsed.sitemaps)
    if not sitemaps:
        out.append(CheckResult("robots", site.name, Status.WARN, M.RB_NO_SITEMAP, {"url": url}))
    else:
        head = ctx.fetcher.request(sitemaps[0], method="HEAD")
        code = head.status
        if head.response is None or code != 200:
            retry = ctx.fetcher.request(sitemaps[0]) if head.response is not None else head
            code = retry.status
            if retry.response is None or code != 200:
                out.append(
                    CheckResult("robots", site.name, Status.WARN,
                                M.RB_SITEMAP_DEAD.format(url=sitemaps[0], status=code or retry.error),
                                {"sitemap": sitemaps[0], "status": code})
                )

    if previous is None:
        out.append(CheckResult("robots", site.name, Status.INFO, M.RB_BASELINE, {"url": url}))
    elif previous != text:
        out.append(
            CheckResult("robots", site.name, Status.WARN, M.RB_CHANGED,
                        {"diff": _diff(previous, text)}, changed=True)
        )

    if ctx.save_state:
        ctx.state.write_text(site.name, STATE_FILE, text)

    if not out:
        out.append(CheckResult("robots", site.name, Status.OK, M.RB_OK,
                               {"sitemaps": sitemaps, "url": url}))
    ctx.extra.setdefault("sitemaps", {})[site.name] = sitemaps
    return out
