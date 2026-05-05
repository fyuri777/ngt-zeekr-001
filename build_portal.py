"""Build static HTML portal from articles/*.md.

Output: portal/index.html (full taxonomy with status) + portal/<slug>.html
Preview: cd portal && python -m http.server 8000
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown

ROOT = Path(__file__).parent
ARTICLES_DIR = ROOT / "articles"
PORTAL_DIR = ROOT / "portal"

# -----------------------------------------------------------------------------
# Taxonomy: full plan for the portal (mirrors taxonomy.md). Each item gets a
# slug if/when its article exists in articles/. Planned items show greyed-out.
# Sub-items (like the buying-used checklist alongside the buying-used article)
# go in "extras".
# -----------------------------------------------------------------------------

TAXONOMY = [
    {
        "id": 1,
        "title": "Начало эксплуатации",
        "priority": "HIGH",
        "items": [
            {"id": "1.1", "title": "Покупка из Китая — процесс, грей-импорт", "slug": "buying-china"},
            {"id": "1.2", "title": "Растаможка — стоимость, документы", "slug": None},
            {"id": "1.3", "title": "Страхование — КАСКО/ОСАГО для китайского EV", "slug": None},
            {"id": "1.4", "title": "Покупка б/у Zeekr 001 — что проверять",
             "slug": "buying-used",
             "extras": [{"title": "Чеклист предпокупочного осмотра", "slug": "buying-used-checklist"}]},
            {"id": "1.5", "title": "Первый запуск и активация", "slug": None},
            {"id": "1.6", "title": "Мастер-аккаунт и Family Account", "slug": "master-account"},
            {"id": "1.7", "title": "Китайский номер и eSIM (WeChat/eSender)", "slug": "chinese-number"},
            {"id": "1.8", "title": "SIM-карта в машине (телематика)", "slug": "car-sim"},
            {"id": "1.9", "title": "Ключи: NFC, телефон, физический", "slug": "keys"},
        ],
    },
    {
        "id": 2,
        "title": "Зарядка",
        "priority": "HIGH",
        "items": [
            {"id": "2.1", "title": "Типы зарядки и разъёмы (AC/DC, GBT, CCS2)", "slug": "charging-types"},
            {"id": "2.2", "title": "Зарядка дома — кабели, розетки, монтаж", "slug": "home-charging"},
            {"id": "2.3", "title": "Публичные сети в России (Punkt E и др.)", "slug": "public-charging-ru"},
            {"id": "2.4", "title": "DC-зарядка — макс. скорость, дорест vs рест", "slug": "dc-charging"},
            {"id": "2.5", "title": "Зимняя зарядка — прогрев батареи, китайское время (см. 3.4)", "slug": "battery-preheat"},
            {"id": "2.6", "title": "Реальный пробег и SOC — сезонные различия", "slug": "range-soc"},
            {"id": "2.7", "title": "V2L — машина как розетка", "slug": "v2l"},
            {"id": "2.8", "title": "Застрявший зарядный кабель — как отсоединить", "slug": None},
        ],
    },
    {
        "id": 3,
        "title": "Здоровье батареи",
        "priority": "HIGH",
        "items": [
            {"id": "3.1", "title": "Антифриз и охлаждение ВВБ — синий vs розовый", "slug": "antifreeze"},
            {"id": "3.2", "title": "12В аккумулятор — логика подзарядки, OBD-донглы", "slug": "battery-12v"},
            {"id": "3.3", "title": "Здоровье ВВБ — хранение, режимы заряда", "slug": "battery-health-storage"},
            {"id": "3.4", "title": "Прогрев батареи — планирование поездки", "slug": "battery-preheat"},
            {"id": "3.5", "title": "Аварийный запуск при севшем 12В", "slug": "emergency-12v"},
        ],
    },
    {
        "id": 4,
        "title": "ПО и прошивки",
        "priority": "HIGH",
        "items": [
            {"id": "4.1", "title": "OTA обновления — версии 5.x дорест / 6.x рест, ZDS", "slug": "ota-versions"},
            {"id": "4.2", "title": "Лучшие версии прошивок — консенсус", "slug": "firmware-best"},
            {"id": "4.3", "title": "Перезагрузки и лаги планшета", "slug": "reboots-lags"},
            {"id": "4.4", "title": "Настройки не сохраняются — баги прошивок", "slug": None},
        ],
    },
    {
        "id": 5,
        "title": "Русификация и связь",
        "priority": "HIGH",
        "items": [
            {"id": "5.1", "title": "Зачем нужна русификация", "slug": None},
            {"id": "5.2", "title": "Сравнение русификаторов — Infohub, GMC, XMETA, ZeeAppStore", "slug": "rusifikators"},
            {"id": "5.3", "title": "Баги русификации и восстановление лаунчера", "slug": None},
            {"id": "5.4", "title": "Интернет в машине — YouTube, VK Video, Telegram без VPN", "slug": None},
            {"id": "5.5", "title": "Яндекс Музыка и Карты — настройка, авторизация", "slug": None},
            {"id": "5.6", "title": "Мобильное приложение МА", "slug": None},
            {"id": "5.7", "title": "ADB-доступ для продвинутых", "slug": None},
        ],
    },
    {
        "id": 6,
        "title": "Двери и доступ",
        "priority": "HIGH",
        "items": [
            {"id": "6.1", "title": "Электронные ручки и двери — устройство и проблемы", "slug": "doors"},
            {"id": "6.2", "title": "Замёрзшие двери и ручки зимой — профилактика", "slug": "frozen-doors"},
            {"id": "6.3", "title": "Безрамочные окна — шум, конденсат, после мойки", "slug": None},
            {"id": "6.4", "title": "Аварийное открытие при севшем 12В (см. 3.5)", "slug": "emergency-12v"},
        ],
    },
    {
        "id": 7,
        "title": "Вождение и фичи",
        "priority": "MEDIUM",
        "items": [
            {"id": "7.1", "title": "Режимы вождения — ECO/Comfort/Sport/Snow, AWD", "slug": "drive-modes"},
            {"id": "7.2", "title": "Пневмоподвеска — режимы, перегрев, город vs трасса", "slug": "air-suspension"},
            {"id": "7.3", "title": "Рекуперация — уровни, прикипающие диски", "slug": None},
            {"id": "7.4", "title": "ADAS / Автопилот — что работает в России", "slug": None},
            {"id": "7.5", "title": "Видеорегистратор (DVR) — запись и хранение", "slug": None},
            {"id": "7.6", "title": "Парковочные функции — авто-парковка", "slug": None},
        ],
    },
    {
        "id": 8,
        "title": "Обслуживание",
        "priority": "MEDIUM",
        "items": [
            {"id": "8.1", "title": "Регламент ТО — официальный vs клубный", "slug": None},
            {"id": "8.2", "title": "Масло — тип, интервал, лабораторный анализ", "slug": None},
            {"id": "8.3", "title": "Антифриз — практика замены (см. 3.1)", "slug": "antifreeze"},
            {"id": "8.4", "title": "Тормозная жидкость и эффект рекуперации на колодки", "slug": None},
            {"id": "8.5", "title": "Салонный фильтр — замена на pre-2023 моделях", "slug": None},
            {"id": "8.6", "title": "Обесточивание (сервисный режим)", "slug": None},
            {"id": "8.7", "title": "Где обслуживать в России — проверенные сервисы", "slug": None},
        ],
    },
    {
        "id": 9,
        "title": "Шины и диски",
        "priority": "MEDIUM",
        "items": [
            {"id": "9.1", "title": "Штатные размеры шин (дорест vs рест)", "slug": None},
            {"id": "9.2", "title": "Давление в шинах — миф 2.0 бар, рекомендации", "slug": "tire-pressure"},
            {"id": "9.3", "title": "Зимние шины — варианты, runflat", "slug": None},
            {"id": "9.4", "title": "Датчики TPMS — замена, программирование", "slug": None},
            {"id": "9.5", "title": "Развал-схождение — когда нужно, специфика 001", "slug": None},
        ],
    },
    {
        "id": 10,
        "title": "Дорест vs Рест",
        "priority": "MEDIUM",
        "items": [
            {"id": "10.1", "title": "Ключевые отличия — железо, ПО, динамика", "slug": None},
            {"id": "10.2", "title": "Прошивки — почему несовместимы (см. 4.1, 4.2)", "slug": "ota-versions"},
            {"id": "10.3", "title": "Совместимость запчастей", "slug": None},
            {"id": "10.4", "title": "Различия зарядки — DC мощность (см. 2.4)", "slug": "dc-charging"},
            {"id": "10.5", "title": "Что покупать — цена, рынок, плюсы/минусы", "slug": None},
        ],
    },
    {
        "id": "B",
        "title": "Бонус: кузов, салон, прочее",
        "priority": "LOW",
        "items": [
            {"id": "B.1", "title": "Защита ЛКП — плёнка vs керамика, лидар", "slug": None},
            {"id": "B.2", "title": "Герметизация фар и фонарей", "slug": None},
            {"id": "B.3", "title": "Запотевание салона — настройки HVAC", "slug": None},
            {"id": "B.4", "title": "Аудиосистема — лимит громкости", "slug": None},
            {"id": "B.5", "title": "Аксессуары и каталожные номера", "slug": None},
            {"id": "B.6", "title": "ПДД и регистрация — нерусские номера, транспортный налог", "slug": None},
        ],
    },
]


CSS = """
:root {
  --bg: #fafaf8;
  --fg: #1a1a1a;
  --muted: #6b6b6b;
  --line: #e5e5e3;
  --accent: #c8390f;
  --link: #2c5282;
  --code-bg: #f0f0ed;
  --planned: #b0b0ab;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
  font-size: 17px;
  line-height: 1.65;
  color: var(--fg);
  background: var(--bg);
}
.wrap { max-width: 760px; margin: 0 auto; padding: 32px 20px 80px; }
header.site { padding: 16px 20px; border-bottom: 1px solid var(--line); background: #fff; }
header.site .inner { max-width: 760px; margin: 0 auto; display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
header.site a { color: var(--fg); text-decoration: none; font-weight: 600; font-size: 18px; }
header.site .sub { color: var(--muted); font-size: 14px; }
nav.crumb { color: var(--muted); font-size: 14px; margin-bottom: 24px; }
nav.crumb a { color: var(--link); text-decoration: none; }
nav.crumb a:hover { text-decoration: underline; }
h1 { font-size: 32px; line-height: 1.2; margin: 0 0 12px; font-weight: 700; }
h2 { font-size: 22px; line-height: 1.3; margin: 40px 0 12px; font-weight: 600; border-top: 1px solid var(--line); padding-top: 32px; }
h2:first-of-type { border-top: none; padding-top: 0; }
h3 { font-size: 18px; margin: 24px 0 8px; font-weight: 600; }
p { margin: 0 0 16px; }
em { color: var(--muted); font-style: italic; }
.lead { font-size: 18px; color: var(--muted); margin-bottom: 32px; font-style: italic; }
ul, ol { padding-left: 24px; margin: 0 0 16px; }
li { margin: 6px 0; }
strong { font-weight: 600; }
hr { border: none; border-top: 1px solid var(--line); margin: 40px 0 24px; }
a { color: var(--link); }
table { border-collapse: collapse; margin: 16px 0; font-size: 15px; }
th, td { border: 1px solid var(--line); padding: 8px 12px; text-align: left; }
th { background: #f0f0ed; font-weight: 600; }
code { background: var(--code-bg); padding: 1px 6px; border-radius: 3px; font-size: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
blockquote { border-left: 3px solid var(--line); padding-left: 16px; margin: 16px 0; color: var(--muted); }
footer.src { margin-top: 48px; padding-top: 24px; border-top: 1px solid var(--line); color: var(--muted); font-size: 14px; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 13px; font-weight: 500; margin-right: 6px; }
.badge-official { background: #e0f2fe; color: #075985; }
.badge-consensus { background: #ecfdf5; color: #065f46; }
.badge-debated { background: #fff7ed; color: #9a3412; }
.badge-stale { background: #fef9c3; color: #854d0e; }
.badge-recent { background: #fae8ff; color: #6b21a8; }
.warning { color: var(--accent); }

/* Index page */
.intro { color: var(--muted); margin: 16px 0 24px; }
.progress {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px 20px;
  margin: 24px 0 32px;
  display: flex;
  gap: 24px;
  align-items: center;
  flex-wrap: wrap;
}
.progress .num { font-size: 28px; font-weight: 700; color: var(--fg); }
.progress .lbl { color: var(--muted); font-size: 14px; }
.progress .bar {
  flex: 1; min-width: 200px; height: 8px; background: var(--line); border-radius: 4px; overflow: hidden;
}
.progress .bar-fill { height: 100%; background: #16a34a; border-radius: 4px; }

.section {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 20px 24px;
  margin-bottom: 16px;
}
.section header {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 12px; margin-bottom: 12px; flex-wrap: wrap;
}
.section header h2 {
  border: none; padding: 0; margin: 0; font-size: 18px;
}
.sec-num { color: var(--muted); font-weight: 500; font-size: 15px; margin-right: 8px; }
.pri { font-size: 12px; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; }
.pri-HIGH { background: #fee2e2; color: #991b1b; }
.pri-MEDIUM { background: #fef3c7; color: #92400e; }
.pri-LOW { background: #f3f4f6; color: #4b5563; }
.section ul { padding-left: 0; margin: 0; list-style: none; }
.section li { padding: 6px 0; border-top: 1px solid var(--line); }
.section li:first-child { border-top: none; }
.item { display: flex; align-items: baseline; gap: 8px; }
.item-id { color: var(--muted); font-size: 13px; min-width: 32px; font-variant-numeric: tabular-nums; }
.item-title { flex: 1; }
.item a { text-decoration: none; }
.item a:hover { text-decoration: underline; }
.item.planned .item-title { color: var(--planned); font-style: italic; }
.status { font-size: 12px; padding: 2px 8px; border-radius: 4px; white-space: nowrap; }
.status.published { background: #dcfce7; color: #166534; }
.status.planned { background: transparent; color: var(--planned); }
.extras { margin-top: 4px; padding-left: 40px; font-size: 14px; color: var(--muted); }
.extras a { color: var(--link); }
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{title} — Zeekr 001</title>
<style>{css}</style>
</head>
<body>
<header class="site">
  <div class="inner">
    <a href="index.html">Zeekr 001 — справочник владельца</a>
    <span class="sub">prototype</span>
  </div>
</header>
<main class="wrap">
<nav class="crumb"><a href="index.html">Главная</a> / {category}</nav>
{body}
</main>
</body>
</html>
"""


CATEGORY_TITLES = {
    "battery-health": "Здоровье батареи",
    "doors-access": "Двери и доступ",
    "tires-wheels": "Шины и диски",
    "ownership-accounts": "Аккаунты и владение",
    "buying-guide": "Покупка",
    "charging": "Зарядка",
    "software": "ПО и прошивки",
    "russification": "Русификация и связь",
    "driving": "Вождение и фичи",
}

# Map known article slugs → category names from topics.yaml
SLUG_CATEGORY = {
    "antifreeze": "battery-health",
    "doors": "doors-access",
    "tire-pressure": "tires-wheels",
    "master-account": "ownership-accounts",
    "chinese-number": "ownership-accounts",
    "car-sim": "ownership-accounts",
    "keys": "ownership-accounts",
    "home-charging": "charging",
    "charging-types": "charging",
    "public-charging-ru": "charging",
    "dc-charging": "charging",
    "range-soc": "battery-health",
    "battery-health-storage": "battery-health",
    "battery-12v": "battery-health",
    "battery-preheat": "battery-health",
    "emergency-12v": "battery-health",
    "ota-versions": "software",
    "firmware-best": "software",
    "reboots-lags": "software",
    "rusifikators": "russification",
    "buying-used": "buying-guide",
    "buying-used-checklist": "buying-guide",
    "buying-china": "buying-guide",
    "v2l": "charging",
    "frozen-doors": "doors-access",
    "drive-modes": "driving",
    "air-suspension": "driving",
}


def replace_inline_badges(html: str) -> str:
    """Convert inline emoji badges to styled span pills."""
    badge_map = {
        "📌 OFFICIAL": '<span class="badge badge-official">📌 OFFICIAL</span>',
        "👥 CONSENSUS": '<span class="badge badge-consensus">👥 CONSENSUS</span>',
        "🔥 DEBATED": '<span class="badge badge-debated">🔥 DEBATED</span>',
        "🔥 ОБСУЖДАЕТСЯ": '<span class="badge badge-debated">🔥 ОБСУЖДАЕТСЯ</span>',
        "⚠️ STALE": '<span class="badge badge-stale">⚠️ STALE</span>',
        "🆕 RECENT": '<span class="badge badge-recent">🆕 RECENT</span>',
        "⚠️ RECENT": '<span class="badge badge-recent">⚠️ RECENT</span>',
    }
    for needle, replacement in badge_map.items():
        html = html.replace(needle, replacement)
    html = re.sub(r"<li>⚠️", '<li class="warning">⚠️', html)
    return html


def parse_article(md_path: Path) -> tuple[str, str, str]:
    """Return (title, lead, body_html)."""
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = ""
    lead = ""
    for i, line in enumerate(lines):
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            for j in range(i + 1, min(i + 6, len(lines))):
                stripped = lines[j].strip()
                if stripped.startswith("*") and stripped.endswith("*") and len(stripped) > 2:
                    lead = stripped[1:-1].strip()
                    break
            break

    html_body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br"],
        output_format="html5",
    )
    if lead:
        html_body = html_body.replace(
            f"<p><em>{lead}</em></p>",
            f'<p class="lead">{lead}</p>',
            1,
        )
    html_body = replace_inline_badges(html_body)
    return title, lead, html_body


def build_index(published_slugs: set[str]) -> str:
    """Render the taxonomy as an index page."""
    total = sum(len(s["items"]) for s in TAXONOMY)
    published_count = sum(
        1 for s in TAXONOMY for it in s["items"]
        if it["slug"] and it["slug"] in published_slugs
    )
    pct = int(round(100 * published_count / total)) if total else 0

    sections_html = []
    for sec in TAXONOMY:
        items_html = []
        for it in sec["items"]:
            slug = it["slug"]
            is_published = slug and slug in published_slugs
            cls = "item" if is_published else "item planned"
            id_html = f'<span class="item-id">{it["id"]}</span>'
            if is_published:
                title_html = f'<span class="item-title"><a href="{slug}.html">{it["title"]}</a></span>'
                status_html = '<span class="status published">опубликовано</span>'
            else:
                title_html = f'<span class="item-title">{it["title"]}</span>'
                status_html = '<span class="status planned">в плане</span>'

            extras_html = ""
            if it.get("extras"):
                ext_lines = []
                for ex in it["extras"]:
                    ex_slug = ex["slug"]
                    if ex_slug and ex_slug in published_slugs:
                        ext_lines.append(f'<a href="{ex_slug}.html">↳ {ex["title"]}</a>')
                    else:
                        ext_lines.append(f'<span style="color:var(--planned)">↳ {ex["title"]} (в плане)</span>')
                extras_html = '<div class="extras">' + " · ".join(ext_lines) + "</div>"

            items_html.append(
                f'<li><div class="{cls}">{id_html}{title_html}{status_html}</div>{extras_html}</li>'
            )

        sec_html = f'''<section class="section">
<header>
  <h2><span class="sec-num">{sec["id"]}.</span>{sec["title"]}</h2>
  <span class="pri pri-{sec["priority"]}">{sec["priority"]}</span>
</header>
<ul>
{chr(10).join(items_html)}
</ul>
</section>'''
        sections_html.append(sec_html)

    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Zeekr 001 — справочник владельца</title>
<style>{CSS}</style>
</head>
<body>
<header class="site">
  <div class="inner">
    <a href="index.html">Zeekr 001 — справочник владельца</a>
    <span class="sub">prototype</span>
  </div>
</header>
<main class="wrap">
<h1>Справочник владельца Zeekr 001</h1>
<p class="intro">Живая база знаний из обсуждений клуба владельцев. Статьи синтезированы из ~131 000 сообщений Telegram-чатов за период август 2024 — май 2026.</p>

<div class="progress">
  <div><div class="num">{published_count}/{total}</div><div class="lbl">статей опубликовано</div></div>
  <div class="bar"><div class="bar-fill" style="width: {pct}%;"></div></div>
  <div><div class="num">{pct}%</div><div class="lbl">прогресс</div></div>
</div>

{chr(10).join(sections_html)}

<footer class="src">
  Полная таксономия — 11 разделов, {total} статей. По мере готовности статьи становятся кликабельными.
</footer>
</main>
</body>
</html>'''


def build():
    PORTAL_DIR.mkdir(exist_ok=True)
    published = set()

    # Render every existing article
    for md_path in sorted(ARTICLES_DIR.glob("*.md")):
        slug = md_path.stem
        title, lead, body = parse_article(md_path)
        category = CATEGORY_TITLES.get(SLUG_CATEGORY.get(slug, ""), "Статья")
        page_html = PAGE_TEMPLATE.format(
            title=title,
            css=CSS,
            category=category,
            body=body,
        )
        (PORTAL_DIR / f"{slug}.html").write_text(page_html, encoding="utf-8")
        published.add(slug)
        print(f"  [ok] {slug}: {len(body)} chars → {slug}.html")

    # Render taxonomy index
    index_html = build_index(published)
    (PORTAL_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"  [ok] index.html → {len(published)} published / {sum(len(s['items']) for s in TAXONOMY)} total")


if __name__ == "__main__":
    build()
    print(f"\nPortal built. Preview:\n  cd {PORTAL_DIR}\n  python -m http.server 8000\nThen open http://localhost:8000/")
