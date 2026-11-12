"""5.4 pages: key pages answer 200, are indexable (portals: the opposite), and look right."""

from __future__ import annotations

from urllib.parse import urlparse

from lxml import html as lxml_html
from protego import Protego

from .. import messages as M
from ..config import Site
from ..context import Context
from ..models import CheckResult, Status

SLOW_SECONDS = 3.0
NOINDEX_METAS = ("robots", "googlebot", "yandex")
UPPER = '"ABCDEFGHIJKLMNOPQRSTUVWXYZ"'
LOWER = '"abcdefghijklmnopqrstuvwxyz"'


def _res(site: Site, status: Status, summary: str, **details) -> CheckResult:
    return CheckResult("pages", site.name, status, summary, details)


def noindex_source(doc, headers) -> str | None:
    """Where a noindex comes from, or None. Checked in both meta tags and the header."""
    tag = headers.get("x-robots-tag", "")
    if "noindex" in tag.lower():
        return "X-Robots-Tag"
    for name in NOINDEX_METAS:
        for meta in doc.xpath(f'//meta[translate(@name,{UPPER},{LOWER})="{name}"]'):
            if "noindex" in (meta.get("content") or "").lower():
                return f'<meta name="{name}">'
    return None


def _first_text(doc, xpath: str) -> str:
    values = doc.xpath(xpath)
    if not values:
        return ""
    value = values[0]
    return (value if isinstance(value, str) else value.text_content()).strip()


def _portal_robots_allows(ctx: Context, site: Site, path: str) -> bool:
    fetch = ctx.fetcher.request(site.canonical + "/robots.txt")
    if fetch.response is None or fetch.response.status_code != 200:
        return True  # no robots.txt = nothing is disallowed
    return Protego.parse(fetch.response.text).can_fetch(site.url(path), "Googlebot")


def run(ctx: Context, site: Site) -> list[CheckResult]:
    out: list[CheckResult] = []
    ok_pages = 0

    for path in site.key_pages:
        url = site.url(path)
        fetch = ctx.fetcher.request(url)
        if fetch.response is None:
            out.append(_res(site, Status.FAIL, M.P_DEAD.format(url=url, error=fetch.error), url=url))
            continue
        response = fetch.response
        if response.status_code != 200:
            out.append(
                _res(site, Status.FAIL, M.P_STATUS.format(url=url, status=response.status_code),
                     url=url, http_status=response.status_code)
            )
            continue
        ok_pages += 1

        if fetch.elapsed > SLOW_SECONDS:
            out.append(_res(site, Status.WARN, M.P_SLOW.format(url=url, seconds=round(fetch.elapsed, 1)),
                            url=url, seconds=round(fetch.elapsed, 2)))

        try:
            doc = lxml_html.fromstring(response.text or "<html></html>")
        except Exception as exc:  # noqa: BLE001 - malformed HTML must not kill the run
            out.append(_res(site, Status.WARN, M.P_STATUS.format(url=url, status="не разобран HTML"),
                            url=url, error=str(exc)[:200]))
            continue

        source = noindex_source(doc, response.headers)

        if site.kind == "portal":
            if source is None and _portal_robots_allows(ctx, site, path):
                out.append(_res(site, Status.WARN, M.P_PORTAL_INDEXABLE.format(url=url), url=url))
            # the login page must not be reachable over plain http
            chain = ctx.fetcher.walk("http://" + urlparse(url).netloc + urlparse(url).path)
            final = chain.final_url or ""
            if not final.startswith("https://"):
                out.append(_res(site, Status.FAIL, M.P_PORTAL_HTTP.format(url=url),
                                url=url, chain=chain.as_dict()))
            own_host = urlparse(site.canonical).netloc
            for action in doc.xpath("//form/@action"):
                host = urlparse(action).netloc
                if host and host != own_host:
                    out.append(_res(site, Status.FAIL, M.P_PORTAL_FORM.format(url=url, host=host),
                                    url=url, action=action))
            continue  # canonical / title / description are not expected on a login page

        if source:
            out.append(_res(site, Status.FAIL, M.P_NOINDEX.format(url=url, source=source),
                            url=url, source=source))

        canonicals = doc.xpath('//link[@rel="canonical"]/@href')
        if not canonicals:
            out.append(_res(site, Status.WARN, M.P_NO_CANONICAL.format(url=url), url=url))
        else:
            found = canonicals[0].strip()
            if found.rstrip("/") != url.rstrip("/"):
                out.append(_res(site, Status.WARN, M.P_CANONICAL.format(url=url, found=found, expected=url),
                                url=url, found=found))

        if not _first_text(doc, "//title"):
            out.append(_res(site, Status.WARN, M.P_TITLE.format(url=url), url=url))
        description = doc.xpath(f'//meta[translate(@name,{UPPER},{LOWER})="description"]/@content')
        if not description or not description[0].strip():
            out.append(_res(site, Status.WARN, M.P_DESC.format(url=url), url=url))

    if not out:
        out.append(_res(site, Status.OK, M.P_OK.format(count=ok_pages), pages=ok_pages))
    return out
