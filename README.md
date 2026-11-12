# Talon — website & domain monitor

Talon checks your websites from the outside and tells you, in one message a day, what broke.

A deploy can silently add `noindex`, block Googlebot in `robots.txt`, break a redirect or let a
certificate lapse — and search engines drop the pages before anyone notices. A DNS record or a
script tag can also change without anyone on the team doing it. Talon watches for both: **breakage**
and **unannounced change**.

It is **read-only**. It sends GET and HEAD requests and DNS queries, nothing else: no logins, no form
posts, no admin endpoints. Login pages are opened and looked at, never submitted to.

```
🧾 Талон — 4 сайта · 1 домен
12.11.2026 · 09:00 MSK

login.example.com
❌ Redirects: http://login.example.com отдаёт 200 без перехода на https
⚠️ Pages: вход https://login.example.com/auth открыт для индексации

example.com
⚠️ Redirects: http://example.com — 2 перехода вместо одного
⚠️ SSL: осталось 12 дней (www.example.com)
⚠️ Headers: нет Strict-Transport-Security

✅ Без замечаний (2): shop.example.com, status.example.com

Итог: 2 ✅ · 1 ⚠️ · 1 ❌
```

*(Example output. The report is written in Russian — the team it was built for works in Russian.
All the strings live in one file, `talon/messages.py`, if you want another language.)*

## What it checks

| Check | Runs on | Catches |
| --- | --- | --- |
| **redirects** | every site | a variant served over plain http, the wrong canonical host, redirect chains and loops, a temporary 302 where a permanent 301 belongs, old URLs that stopped redirecting |
| **robots** | marketing sites | the whole site closed off, a key page blocked for Googlebot or YandexBot, AI crawlers newly blocked, any change to the file (with a diff) |
| **sitemap** | marketing sites | sitemap missing, broken XML, dead or redirecting URLs, the URL count collapsing |
| **pages** | every site | a key page not answering 200, `noindex` in a meta tag or the `X-Robots-Tag` header, a wrong or missing canonical, an empty title or description, a slow page |
| **pages** (login portals) | portals | a login page that search engines may index, a login page reachable over plain http, a login form whose `action` points at another host |
| **ssl** | every site | a certificate that does not cover the host, expiry inside 21 days (warn) or 7 days (fail), a changed issuer |
| **dns** | every domain | A / AAAA / CNAME / MX / NS changed (fail), TXT / CAA changed (warn), public resolvers disagreeing with the authoritative nameserver, registrar or nameservers changed at the registrar, the domain expiring |
| **content** | every site | the visible text of a key page changed (with a diff), a new external script, iframe or stylesheet domain, a changed title, canonical or navigation |
| **headers** | marketing sites, portals | no `Strict-Transport-Security`, a `Server` header giving away its version |

Four statuses: ✅ ok · ⚠️ warn (fix it, not urgent) · ❌ fail (hurting indexing, users or security
right now) · ℹ️ info (nothing was judged — a baseline was saved, or RDAP is unavailable for that TLD).
Info never counts as a problem.

The first run for a site records the baseline and reports nothing as changed. Change alerts start
with the second run.

## Install

```bash
git clone https://github.com/elkushi/talon.git && cd talon
python3.12 -m venv .venv
.venv/bin/pip install httpx lxml dnspython protego PyYAML
cp config.example.yaml config.yaml     # describe your sites here
cp .env.example .env                   # Telegram bot token + chat id
.venv/bin/python -m talon --mode daily --dry-run
```

`--dry-run` prints the report instead of sending it, so you can try it before any bot exists.

## Telegram

The API needs a numeric **chat id**, not an @nickname (an @name only works for public channels).

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → put the token in `.env` as `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message — privately, or add it to the team group (with permission to post)
   and write there.
3. `.venv/bin/python tools/chat_id.py` lists the chats the bot can see. Put the one you want in
   `.env` as `TELEGRAM_CHAT_ID` (group ids are negative).
4. `.venv/bin/python tools/chat_id.py --test` posts one test message.

**Secrets never go in `config.yaml`.** The config only names the environment variables to read; the
token and chat id live in `.env`, which is gitignored. Nothing is logged that contains them.

## Running it

| Command | What it does |
| --- | --- |
| `python -m talon --mode daily` | every check, always posts the report |
| `python -m talon --mode watch` | dns + content + certificate issuer only, posts **only** when something changed or failed |
| `python -m talon --mode daily --dry-run` | prints instead of sending |
| `python -m talon --accept example.com/dns` | accept the current state as the new baseline, after a change you made on purpose |

Exit code 0 for a completed run (even when checks fail), 1 for an internal error — and on an internal
error it still tries to post "the run did not complete, because …", so silence is never mistaken for
good news.

The evidence behind every line — redirect chains, diffs, DNS record sets — goes to
`logs/report-<date>-<mode>.json`. The chat gets the short version.

## Deploying

`deploy/crontab.example`: the daily report at 09:00, the change watch hourly.

```
0 9 * * *  cd /opt/talon && .venv/bin/python -m talon --mode daily >> logs/cron.log 2>&1
5 * * * *  cd /opt/talon && .venv/bin/python -m talon --mode watch >> logs/cron.log 2>&1
```

Run it on a machine that does **not** host the sites it watches, or an outage takes the monitor down
with them. `deploy/github-actions.yml` is the alternative: GitHub Actions on a schedule, with the
baseline kept on a dedicated `state` branch.

## How it is built

Python 3.12, no database. `httpx` with redirects followed by hand so every hop is recorded, `protego`
for Google-compatible robots.txt matching, `lxml` for HTML and sitemap XML, `dnspython` for DNS,
the standard library for TLS.

- Every check returns the same `CheckResult`, so the report has one shape to render.
- A check that crashes is caught, logged with its traceback and reported as one failed check. One
  broken check never takes the run down.
- A failed request never overwrites a baseline, so a network blip can't become "the new normal".
- Every request gets one retry after 5 seconds before a host is called unreachable.
- State is written atomically (temp file, then `os.replace`).
- Nothing about any site is hard-coded: hosts, key pages, expected DNS records and allowed external
  domains all live in `config.yaml`, and the tool refuses to run while a value is still `TODO`.

Tests run against fixtures and mocked HTTP only — never the live internet:

```bash
.venv/bin/pip install pytest respx ruff
.venv/bin/python -m pytest -q      # 64 tests
.venv/bin/python -m ruff check talon tests
```

## What it does not do

It tells you **what** changed and **when**. It cannot tell you **who** — that needs per-user accounts
and audit logs at your registrar, DNS provider and hosting. Treat a change alert as a question to ask,
not an answer.

MIT licensed.
