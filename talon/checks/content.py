"""5.7 content: catch an unannounced change to a page - text, scripts, title, nav links."""

from __future__ import annotations

import difflib
import hashlib
import re
from urllib.parse import urlparse

from lxml import html as lxml_html

from .. import messages as M
from ..config import Site
from ..context import Context
from ..models import CheckResult, Status

MAX_DIFF_LINES = 20
DROP_TAGS = ("script", "style", "noscript", "template", "svg")
WHITESPACE = re.compile(r"\s+")
UPPER = '"ABCDEFGHIJKLMNOPQRSTUVWXYZ"'
LOWER = '"abcdefghijklmnopqrstuvwxyz"'


def normalise(html_text: str, ignore_patterns: list[str]) -> str:
    """Visible text only, whitespace collapsed, volatile bits (tokens, dates) removed."""
    doc = lxml_html.fromstring(html_text or "<html></html>")
    for tag in DROP_TAGS:
        for node in doc.xpath(f"//{tag}"):
            node.getparent().remove(node)
    text = doc.text_content()
    for pattern in ignore_patterns:
        text = re.sub(pattern, "", text)
    text = WHITESPACE.sub(" ", text).strip()
    return text


def external_domains(doc, own_host: str) -> list[str]:
    urls: list[str] = []
    urls += doc.xpath("//script/@src")
    urls += doc.xpath("//iframe/@src")
    urls += doc.xpath(f'//link[contains(translate(@rel,{UPPER},{LOWER}),"stylesheet")]/@href')
    urls += doc.xpath("//form/@action")
    hosts = set()
    for url in urls:
        host = urlparse(url.strip()).netloc.lower()
        if host and host != own_host:
            hosts.add(host)
    return sorted(hosts)


def _diff(old: str, new: str) -> list[str]:
    return list(
        difflib.unified_diff(old.split(" "), new.split(" "), fromfile="было", tofile="стало", lineterm="", n=3)
    )[:MAX_DIFF_LINES]


def run(ctx: Context, site: Site) -> list[CheckResult]:
    out: list[CheckResult] = []
    own_host = urlparse(site.canonical).netloc.lower()
    baselined = 0

    for path in site.key_pages:
        url = site.url(path)
        slug = ctx.state.slug(path)
        fetch = ctx.fetcher.request(url)
        if fetch.response is None or fetch.response.status_code != 200:
            out.append(
                CheckResult("content", site.name, Status.WARN,
                            M.C_DEAD.format(url=url, error=fetch.error or f"код {fetch.status}"),
                            {"url": url, "status": fetch.status})
            )
            continue

        html_text = fetch.response.text
        try:
            doc = lxml_html.fromstring(html_text or "<html></html>")
        except Exception as exc:  # noqa: BLE001
            out.append(CheckResult("content", site.name, Status.WARN,
                                   M.C_DEAD.format(url=url, error=f"HTML не разобран: {exc}"[:120]),
                                   {"url": url}))
            continue

        text = normalise(html_text, ctx.config.ignore_patterns)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        title = (doc.xpath("//title/text()") or [""])[0].strip()
        canonical = (doc.xpath('//link[@rel="canonical"]/@href') or [""])[0].strip()
        nav = sorted({h.strip() for h in doc.xpath("//header//a/@href | //footer//a/@href")})
        externals = external_domains(doc, own_host)

        old_meta = ctx.state.read_json(site.name, f"content/{slug}.json")
        old_text = ctx.state.read_text(site.name, f"content/{slug}.txt")

        if old_meta is None:
            baselined += 1
        else:
            if old_meta.get("hash") != digest:
                out.append(
                    CheckResult("content", site.name, Status.WARN, M.C_CHANGED.format(path=path),
                                {"url": url, "diff": _diff(old_text or "", text)}, changed=True)
                )
            known = set(old_meta.get("external_domains") or []) | set(ctx.config.allowed_external_domains)
            new_hosts = [h for h in externals if h not in known]
            if new_hosts:
                out.append(
                    CheckResult("content", site.name, Status.FAIL,
                                M.C_EXTERNAL.format(path=path, domains=", ".join(new_hosts)),
                                {"url": url, "new": new_hosts, "known": sorted(known)}, changed=True)
                )
            if old_meta.get("title") and old_meta["title"] != title:
                out.append(
                    CheckResult("content", site.name, Status.WARN,
                                M.C_TITLE.format(path=path, old=old_meta["title"], new=title),
                                {"url": url}, changed=True)
                )
            if old_meta.get("canonical") and old_meta["canonical"] != canonical:
                out.append(
                    CheckResult("content", site.name, Status.WARN,
                                M.P_CANONICAL.format(url=url, found=canonical, expected=old_meta["canonical"]),
                                {"url": url}, changed=True)
                )
            if old_meta.get("nav") is not None and old_meta["nav"] != nav:
                out.append(
                    CheckResult("content", site.name, Status.WARN, M.C_LINKS.format(path=path),
                                {"url": url, "old": old_meta["nav"], "new": nav}, changed=True)
                )

        if ctx.save_state:
            ctx.state.write_text(site.name, f"content/{slug}.txt", text)
            ctx.state.write_json(site.name, f"content/{slug}.json", {
                "hash": digest,
                "title": title,
                "canonical": canonical,
                "nav": nav,
                "external_domains": externals,
                "url": url,
                "checked_at": ctx.now.isoformat(timespec="seconds"),
            })

    if baselined:
        out.append(CheckResult("content", site.name, Status.INFO, M.C_BASELINE.format(count=baselined), {}))
    if not out:
        out.append(CheckResult("content", site.name, Status.OK, M.C_OK, {}))
    return out
