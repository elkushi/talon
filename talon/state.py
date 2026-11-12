"""Small JSON/text files under state/. No database."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _safe(name: str) -> str:
    """Make a domain or page path usable as a file name."""
    out = "".join(c if c.isalnum() or c in "-._" else "_" for c in name)
    return out.strip("_") or "root"


class State:
    """Reads and writes the baseline files. Writes are atomic (temp file + os.replace)."""

    def __init__(self, root: Path | str = "state") -> None:
        self.root = Path(root)

    # --- paths -------------------------------------------------------------
    def domain_dir(self, domain: str) -> Path:
        return self.root / _safe(domain)

    def path(self, domain: str, *parts: str) -> Path:
        return self.domain_dir(domain).joinpath(*parts)

    @staticmethod
    def slug(page_path: str) -> str:
        return _safe(page_path.strip("/") or "root")

    # --- read --------------------------------------------------------------
    def read_text(self, domain: str, name: str) -> str | None:
        p = self.path(domain, name)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def read_json(self, domain: str, name: str) -> dict | None:
        raw = self.read_text(domain, name)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    # --- write -------------------------------------------------------------
    def write_text(self, domain: str, name: str, text: str) -> None:
        p = self.path(domain, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)

    def write_json(self, domain: str, name: str, data: dict) -> None:
        self.write_text(domain, name, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))

    # --- global ------------------------------------------------------------
    def read_last_run(self) -> dict:
        p = self.root / "last_run.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def write_last_run(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.root / "last_run.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)

    # --- accept ------------------------------------------------------------
    # Files each check owns, so --accept <domain>/<check> can reset exactly one baseline.
    CHECK_FILES: dict[str, list[str]] = {
        "robots": ["robots.txt"],
        "sitemap": ["sitemap.json"],
        "ssl": ["ssl.json"],
        "ssl_cert": ["ssl.json"],
        "dns": ["dns.json"],
        "dns_records": ["dns.json"],
        "content": ["content"],
    }

    def accept(self, domain: str, check: str) -> list[str]:
        """Drop the stored baseline for one check, so the next run saves a new one.

        Returns the paths removed. Unknown check -> ValueError, so a typo is not silently ignored.
        """
        if check not in self.CHECK_FILES:
            known = ", ".join(sorted(set(self.CHECK_FILES)))
            raise ValueError(f"unknown check '{check}' (known: {known})")
        removed: list[str] = []
        for name in self.CHECK_FILES[check]:
            p = self.path(domain, name)
            if p.is_dir():
                shutil.rmtree(p)
                removed.append(str(p))
            elif p.exists():
                p.unlink()
                removed.append(str(p))
        return removed
