"""5.8 headers: HSTS present, Server header not leaking a version."""

from __future__ import annotations

import re

from .. import messages as M
from ..config import Site
from ..context import Context
from ..models import CheckResult, Status

VERSION = re.compile(r"\d+\.\d+")


def run(ctx: Context, site: Site) -> list[CheckResult]:
    fetch = ctx.fetcher.request(site.canonical + "/")
    if fetch.response is None:
        return [
            CheckResult(
                "headers", site.name, Status.WARN,
                M.R_DEAD.format(url=site.canonical, error=fetch.error), {"error": fetch.error},
            )
        ]
    headers = fetch.response.headers
    out: list[CheckResult] = []
    if "strict-transport-security" not in headers:
        out.append(CheckResult("headers", site.name, Status.WARN, M.H_NO_HSTS, {"headers": dict(headers)}))
    server = headers.get("server", "")
    if server and VERSION.search(server):
        out.append(
            CheckResult("headers", site.name, Status.WARN, M.H_SERVER.format(value=server), {"server": server})
        )
    if not out:
        out.append(CheckResult("headers", site.name, Status.OK, M.H_OK, {"server": server}))
    return out
