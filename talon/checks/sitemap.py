"""5.3 sitemap: the map search engines read must exist, parse, and point at live pages.

Per-URL problems are aggregated into one line (the талон has to stay short); every bad URL
is listed in `details`, and the run log keeps the full list.
"""

from __future__ import annotations

import httpx
from lxml import etree

from .. import messages as M
from ..config import Site
from ..context import Context
from ..models import CheckResult, Status

STATE_FILE = "sitemap.json"
MAX_DEPTH = 2
EXAMPLES = 10


def _parse(xml: bytes) -> tuple[list[str], list[str]]:
    """Return (page urls, nested sitemap urls). Raises etree.XMLSyntaxError on bad XML."""
    root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    tag = etree.QName(root).localname
    locs = [e.text.strip() for e in root.findall(".//sm:loc", ns) if e.text and e.text.strip()]
    if not locs:  # sitemap without the standard namespace
        locs = [e.text.strip() for e in root.iter() if etree.QName(e).localname == "loc" and e.text]
    if tag == "sitemapindex":
        return [], locs
    return locs, []


def _collect(ctx: Context, site: Site, start: list[str]) -> tuple[list[str], list[CheckResult]]:
    urls: list[str] = []
    problems: list[CheckResult] = []
    queue = [(u, 1) for u in start]
    seen: set[str] = set()
    while queue:
        url, depth = queue.pop(0)
        if url in seen or depth > MAX_DEPTH:
            continue
        seen.add(url)
        fetch = ctx.fetcher.request(url)
        # a sitemap that 301s to the canonical host still works for crawlers: follow it, but say so
        hops = 0
        while (
            fetch.response is not None
            and 300 <= fetch.response.status_code < 400
            and fetch.response.headers.get("location")
            and hops < 3
        ):
            final = str(httpx.URL(url).join(fetch.response.headers["location"]))
            problems.append(
                CheckResult("sitemap", site.name, Status.WARN,
                            M.SM_REDIRECT.format(url=url, status=fetch.response.status_code, final=final),
                            {"sitemap": url, "final": final})
            )
            fetch = ctx.fetcher.request(final)
            hops += 1
        if fetch.response is None or fetch.response.status_code != 200:
            problem = fetch.error or f"код {fetch.status}"
            problems.append(
                CheckResult("sitemap", site.name, Status.FAIL, M.SM_DEAD.format(url=url, problem=problem),
                            {"sitemap": url, "status": fetch.status, "error": fetch.error})
            )
            continue
        try:
            pages, nested = _parse(fetch.response.content)
        except etree.XMLSyntaxError as exc:
            problems.append(
                CheckResult("sitemap", site.name, Status.FAIL, M.SM_BAD_XML.format(url=url),
                            {"sitemap": url, "error": str(exc)[:200]})
            )
            continue
        urls.extend(pages)
        queue.extend((n, depth + 1) for n in nested)
    return urls, problems


def run(ctx: Context, site: Site) -> list[CheckResult]:
    sources = ctx.extra.get("sitemaps", {}).get(site.name) or site.sitemaps
    if not sources:
        return [CheckResult("sitemap", site.name, Status.WARN, M.SM_NONE, {})]

    urls, out = _collect(ctx, site, list(sources))
    if not urls:
        return out or [CheckResult("sitemap", site.name, Status.WARN, M.SM_NONE, {"sources": sources})]

    total = len(urls)
    foreign = [u for u in urls if not u.startswith(site.canonical)]
    if foreign:
        out.append(
            CheckResult("sitemap", site.name, Status.WARN,
                        M.SM_URL_FOREIGN.format(count=len(foreign), canonical=site.canonical),
                        {"examples": foreign[:EXAMPLES]})
        )

    to_check = urls[: ctx.config.sitemap_max_urls]
    bad: list[dict] = []
    for url in to_check:
        fetch = ctx.fetcher.request(url, method="HEAD")
        if fetch.response is None or fetch.response.status_code in (405, 501):
            fetch = ctx.fetcher.request(url)
        code = fetch.status
        if fetch.response is None or code != 200:
            bad.append({"url": url, "status": code, "error": fetch.error})

    if bad:
        share = len(bad) / len(to_check)
        status = Status.FAIL if share > 0.10 else Status.WARN
        out.append(
            CheckResult("sitemap", site.name, status,
                        M.SM_URL_BAD.format(bad=len(bad), checked=len(to_check)),
                        {"share": round(share, 3), "examples": bad[:EXAMPLES]})
        )

    previous = ctx.state.read_json(site.name, STATE_FILE)
    if previous is None:
        out.append(CheckResult("sitemap", site.name, Status.INFO, M.SM_BASELINE.format(total=total),
                               {"total": total}))
    else:
        old = int(previous.get("url_count", 0))
        if old and abs(total - old) / old > 0.20:
            out.append(
                CheckResult("sitemap", site.name, Status.WARN, M.SM_COUNT.format(old=old, new=total),
                            {"old": old, "new": total}, changed=True)
            )

    if ctx.save_state:
        ctx.state.write_json(site.name, STATE_FILE, {
            "url_count": total,
            "checked": len(to_check),
            "sources": list(sources),
            "checked_at": ctx.now.isoformat(timespec="seconds"),
        })

    if not out:
        out.append(
            CheckResult("sitemap", site.name, Status.OK,
                        M.SM_OK.format(total=total, checked=len(to_check)), {"total": total})
        )
    return out
