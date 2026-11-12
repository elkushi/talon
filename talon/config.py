"""Load and validate config.yaml. All site data lives here, never in code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TODO = "TODO"

# Which checks run on which kind of site (CLAUDE.md 1a). dns runs per registrable domain.
CHECKS_BY_KIND: dict[str, tuple[str, ...]] = {
    "marketing": ("redirects", "robots", "sitemap", "pages", "ssl", "content", "headers"),
    "portal": ("redirects", "pages", "ssl", "content", "headers"),
    "app": ("redirects", "pages", "ssl", "content"),
}

WATCH_CHECKS: tuple[str, ...] = ("dns", "content", "ssl")


class ConfigError(Exception):
    """Config is missing, malformed, or still has TODO placeholders."""


@dataclass
class Site:
    name: str
    kind: str
    canonical: str
    variants: list[str] = field(default_factory=list)
    key_pages: list[str] = field(default_factory=lambda: ["/"])
    legacy_redirects: dict[str, str] = field(default_factory=dict)
    sitemaps: list[str] = field(default_factory=list)

    @property
    def checks(self) -> tuple[str, ...]:
        return CHECKS_BY_KIND[self.kind]

    @property
    def hosts(self) -> list[str]:
        """Every https host this site is reached by, deduplicated, in config order."""
        out: list[str] = []
        for url in [self.canonical, *self.variants]:
            host = url.split("://", 1)[-1].split("/", 1)[0]
            if host and host not in out:
                out.append(host)
        return out

    def url(self, path: str) -> str:
        return self.canonical.rstrip("/") + "/" + path.lstrip("/")


@dataclass
class DnsDomain:
    name: str
    expected: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Config:
    timezone: str = "Europe/Moscow"
    sites: list[Site] = field(default_factory=list)
    dns_domains: list[DnsDomain] = field(default_factory=list)
    bots: dict[str, list[str]] = field(default_factory=dict)
    http: dict[str, Any] = field(default_factory=dict)
    sitemap: dict[str, Any] = field(default_factory=dict)
    ssl: dict[str, Any] = field(default_factory=dict)
    dns: dict[str, Any] = field(default_factory=dict)
    content: dict[str, Any] = field(default_factory=dict)
    telegram: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    # --- convenience accessors with the defaults from CLAUDE.md -------------
    @property
    def retry_after_seconds(self) -> float:
        return float(self.http.get("retry_once_after_seconds", 5))

    @property
    def sitemap_max_urls(self) -> int:
        return int(self.sitemap.get("max_urls", 500))

    @property
    def ssl_warn_days(self) -> int:
        return int(self.ssl.get("warn_days", 21))

    @property
    def ssl_fail_days(self) -> int:
        return int(self.ssl.get("fail_days", 7))

    @property
    def allowed_issuers(self) -> list[str]:
        return list(self.ssl.get("allowed_issuers") or [])

    @property
    def resolvers(self) -> list[str]:
        return list(self.dns.get("resolvers") or ["1.1.1.1", "8.8.8.8"])

    @property
    def record_types(self) -> list[str]:
        return list(self.dns.get("record_types") or ["A", "AAAA", "CNAME", "MX", "NS", "TXT", "CAA"])

    @property
    def rdap_enabled(self) -> bool:
        return bool(self.dns.get("rdap", True))

    @property
    def search_bots(self) -> list[str]:
        return list(self.bots.get("search") or ["Googlebot", "YandexBot"])

    @property
    def ai_bots(self) -> list[str]:
        return list(self.bots.get("ai") or [])

    @property
    def ignore_patterns(self) -> list[str]:
        return list(self.content.get("ignore_patterns") or [])

    @property
    def allowed_external_domains(self) -> list[str]:
        return list(self.content.get("allowed_external_domains") or [])

    @property
    def mention_on_fail(self) -> list[str]:
        return list(self.telegram.get("mention_on_fail") or [])

    def site(self, name: str) -> Site | None:
        return next((s for s in self.sites if s.name == name), None)

    # --- validation --------------------------------------------------------
    def todos(self) -> list[str]:
        """Config keys still holding the literal TODO. Empty list = ready to run for real."""
        found: list[str] = []

        def scan(value: Any, where: str) -> None:
            if isinstance(value, str) and value.strip().startswith(TODO):
                found.append(where)
            elif isinstance(value, dict):
                for k, v in value.items():
                    scan(v, f"{where}.{k}")
            elif isinstance(value, list):
                for i, v in enumerate(value):
                    scan(v, f"{where}[{i}]")

        for s in self.sites:
            scan(s.canonical, f"sites.{s.name}.canonical")
            scan(s.variants, f"sites.{s.name}.variants")
            scan(s.key_pages, f"sites.{s.name}.key_pages")
            scan(s.legacy_redirects, f"sites.{s.name}.legacy_redirects")
        for d in self.dns_domains:
            scan(d.expected, f"dns_domains.{d.name}.expected")
        scan(self.telegram.get("mention_on_fail", []), "telegram.mention_on_fail")
        return found


def _merge_defaults(raw_site: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    merged.update(raw_site)
    return merged


def load(path: str | Path) -> Config:
    """Read config.yaml into a Config. Raises ConfigError with a clear message on bad input."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config not found: {p} (copy config.example.yaml to config.yaml)")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{p} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{p}: top level must be a mapping")

    defaults = raw.get("defaults") or {}
    sites: list[Site] = []
    for i, item in enumerate(raw.get("sites") or []):
        if not isinstance(item, dict):
            raise ConfigError(f"sites[{i}] must be a mapping")
        merged = _merge_defaults(item, defaults)
        for required in ("name", "kind", "canonical"):
            if required not in merged:
                raise ConfigError(f"sites[{i}]: missing '{required}'")
        if merged["kind"] not in CHECKS_BY_KIND:
            raise ConfigError(
                f"sites[{i}] ({merged['name']}): kind '{merged['kind']}' is not one of "
                f"{', '.join(CHECKS_BY_KIND)}"
            )
        sites.append(
            Site(
                name=str(merged["name"]),
                kind=str(merged["kind"]),
                canonical=str(merged["canonical"]).rstrip("/"),
                variants=[str(v) for v in (merged.get("variants") or [])],
                key_pages=[str(v) for v in (merged.get("key_pages") or ["/"])],
                legacy_redirects={str(k): str(v) for k, v in (merged.get("legacy_redirects") or {}).items()},
                sitemaps=[str(v) for v in (merged.get("sitemaps") or [])],
            )
        )
    if not sites:
        raise ConfigError(f"{p}: no sites configured")

    names = [s.name for s in sites]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ConfigError(f"{p}: duplicate site names: {', '.join(sorted(dupes))}")

    dns_domains = [
        DnsDomain(name=str(name), expected=(item or {}).get("expected") or {})
        for name, item in (raw.get("dns_domains") or {}).items()
    ]

    return Config(
        timezone=str(raw.get("timezone", "Europe/Moscow")),
        sites=sites,
        dns_domains=dns_domains,
        bots=raw.get("bots") or {},
        http=raw.get("http") or {},
        sitemap=raw.get("sitemap") or {},
        ssl=raw.get("ssl") or {},
        dns=raw.get("dns") or {},
        content=raw.get("content") or {},
        telegram=raw.get("telegram") or {},
        path=p,
    )
