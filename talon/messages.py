"""Every Russian string in one place (CLAUDE.md 13). Checks fill these templates."""

from __future__ import annotations

RETRY_OK = "повтор успешен"

# --- redirects ---------------------------------------------------------------
R_OK = "Redirects: {url} → {target} (один переход 301)"
R_CANONICAL_OK = "Redirects: {url} отвечает 200 без переходов"
R_CANONICAL_REDIRECTS = "Redirects: основной адрес {url} сам перенаправляет на {target}"
R_NO_HTTPS = "Redirects: {url} отдаёт {status} без перехода на https"
R_WRONG_TARGET = "Redirects: {url} ведёт на {final}, а должен на {target}"
R_BAD_FINAL = "Redirects: {url} заканчивается кодом {status}"
R_DEAD = "Redirects: {url} недоступен ({error})"
R_TLS = "Redirects: ошибка TLS на {url} ({error})"
R_LOOP = "Redirects: петля переходов на {url}"
R_TEMP = "Redirects: {url} использует временный {status} вместо 301"
R_MANY_HOPS = "Redirects: {url} — {hops} перехода вместо одного"
R_LEGACY_OK = "Redirects: старый адрес {path} ведёт на {target}"
R_LEGACY_BAD = "Redirects: старый адрес {path} не ведёт на {target} ({problem})"

# --- robots ------------------------------------------------------------------
RB_OK = "Robots: в порядке"
RB_DOWN = "Robots: robots.txt недоступен ({problem})"
RB_404 = "Robots: robots.txt отдаёт 404"
RB_TYPE = "Robots: Content-Type {ctype} вместо text/plain"
RB_DISALLOW_ALL = "Robots: весь сайт закрыт от индексации (Disallow: / для *)"
RB_PAGE_BLOCKED = "Robots: {bot} не пускают на {path}"
RB_AI_BLOCKED = "Robots: {bot} закрыли доступ к {path} (было открыто)"
RB_NO_SITEMAP = "Robots: нет строки Sitemap:"
RB_SITEMAP_DEAD = "Robots: Sitemap {url} отдаёт {status}"
RB_CHANGED = "Robots: файл изменился"
RB_BASELINE = "Robots: базовая линия сохранена"

# --- sitemap -----------------------------------------------------------------
SM_OK = "Sitemap: {total} URL, проверено {checked}, все 200"
SM_NONE = "Sitemap: не найден ни в robots.txt, ни в конфиге"
SM_DEAD = "Sitemap: {url} недоступен ({problem})"
SM_BAD_XML = "Sitemap: {url} — некорректный XML"
SM_REDIRECT = "Sitemap: {url} отвечает {status} и ведёт на {final}"
SM_URL_BAD = "Sitemap: {bad} из {checked} URL отвечают не 200 напрямую"
SM_URL_FOREIGN = "Sitemap: {count} URL вне {canonical}"
SM_COUNT = "Sitemap: число URL изменилось {old} → {new}"
SM_BASELINE = "Sitemap: базовая линия сохранена ({total} URL)"

# --- pages -------------------------------------------------------------------
P_OK = "Pages: {count} страниц, все 200"
P_STATUS = "Pages: {url} отдаёт {status}"
P_DEAD = "Pages: {url} недоступна ({error})"
P_NOINDEX = "Pages: на {url} стоит noindex ({source})"
P_CANONICAL = "Pages: canonical на {url} ведёт на {found}, а должен на {expected}"
P_NO_CANONICAL = "Pages: на {url} нет canonical"
P_TITLE = "Pages: на {url} пустой <title>"
P_DESC = "Pages: на {url} нет meta description"
P_SLOW = "Pages: {url} отвечает {seconds} с"
P_PORTAL_INDEXABLE = "Pages: вход {url} открыт для индексации (нет noindex и не закрыт в robots.txt)"
P_PORTAL_HTTP = "Pages: вход {url} по http:// не переходит на https"
P_PORTAL_FORM = "Pages: форма входа на {url} отправляет данные на чужой хост {host}"

# --- ssl ---------------------------------------------------------------------
S_OK = "SSL: ещё {days} дней ({host})"
S_EXPIRING = "SSL: осталось {days} дней ({host})"
S_INVALID = "SSL: сертификат не проходит проверку для {host} ({error})"
S_UNREACHABLE = "SSL: {host} не ответил по https ({error})"
S_HOSTNAME = "SSL: сертификат не покрывает {host}"
S_ISSUER = "SSL: сменился издатель сертификата {host}: {old} → {new}"
S_BASELINE = "SSL: базовая линия сохранена ({host}, {issuer})"

# --- dns ---------------------------------------------------------------------
D_OK = "DNS: записи без изменений"
D_CHANGED = "DNS: {rtype} изменились: {old} → {new}"
D_UNEXPECTED = "DNS: {rtype} не совпадают с ожидаемыми: {actual} вместо {expected}"
D_DISAGREE = "DNS: резолверы расходятся с авторитетным NS по {rtype}"
D_ERROR = "DNS: запрос {rtype} не выполнен ({error})"
D_BASELINE = "DNS: базовая линия сохранена"
D_RDAP_REGISTRAR = "DNS: сменился регистратор: {old} → {new}"
D_RDAP_NS = "DNS: сменились NS у регистратора: {old} → {new}"
D_RDAP_EXPIRY = "DNS: домен истекает через {days} дней ({date})"
D_RDAP_NONE = "DNS: RDAP недоступен для домена"

# --- content -----------------------------------------------------------------
C_OK = "Content: без изменений"
C_CHANGED = "Content: текст {path} изменился"
C_EXTERNAL = "Content: новый внешний ресурс на {path}: {domains}"
C_TITLE = "Content: изменился <title> на {path}: «{old}» → «{new}»"
C_LINKS = "Content: изменились ссылки в шапке/подвале на {path}"
C_BASELINE = "Content: базовая линия сохранена ({count} страниц)"
C_DEAD = "Content: {url} недоступна ({error})"

# --- headers -----------------------------------------------------------------
H_OK = "Headers: в порядке"
H_NO_HSTS = "Headers: нет Strict-Transport-Security"
H_SERVER = "Headers: заголовок Server раскрывает версию ({value})"

# --- run ---------------------------------------------------------------------
CHECK_CRASHED = "{check}: проверка не выполнена ({exc})"
RUN_FAILED = "❌ Талон: проверка не выполнена — {reason}"
SITE_SKIPPED = "Config: {name} пропущен — не выбран основной адрес (canonical: TODO)"
