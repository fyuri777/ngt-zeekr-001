"""Build static HTML portal from articles/*.md.

Output: portal/index.html + portal/<slug>.html
Preview: cd portal && python -m http.server 8000
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).parent
ARTICLES_DIR = ROOT / "articles"
PORTAL_DIR = ROOT / "portal"

CSS = """
:root {
  --bg: #fafaf8;
  --fg: #1a1a1a;
  --muted: #6b6b6b;
  --line: #e5e5e3;
  --accent: #c8390f;
  --link: #2c5282;
  --code-bg: #f0f0ed;
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
.wrap { max-width: 720px; margin: 0 auto; padding: 32px 20px 80px; }
header.site { padding: 16px 20px; border-bottom: 1px solid var(--line); background: #fff; }
header.site .inner { max-width: 720px; margin: 0 auto; display: flex; align-items: baseline; justify-content: space-between; }
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
footer.src em { font-style: italic; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 13px; font-weight: 500; margin-right: 6px; }
.badge-official { background: #e0f2fe; color: #075985; }
.badge-consensus { background: #ecfdf5; color: #065f46; }
.badge-debated { background: #fff7ed; color: #9a3412; }
.badge-stale { background: #fef9c3; color: #854d0e; }
.badge-recent { background: #fae8ff; color: #6b21a8; }
.warning { color: var(--accent); }

/* Index page */
.cards { display: grid; gap: 16px; margin-top: 24px; }
.card {
  display: block;
  padding: 24px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s, transform 0.15s;
}
.card:hover { border-color: #c0c0bd; transform: translateY(-1px); }
.card h2 { border: none; padding: 0; margin: 0 0 8px; font-size: 20px; color: var(--fg); }
.card p { margin: 0; color: var(--muted); font-size: 15px; line-height: 1.5; }
.intro { color: var(--muted); margin: 16px 0 32px; }
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

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Zeekr 001 — справочник владельца</title>
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
<h1>Справочник владельца Zeekr 001</h1>
<p class="intro">Живая база знаний из обсуждений клуба владельцев. Статьи синтезированы из {total_msgs}+ сообщений Telegram-чата за период август 2024 — май 2026.</p>
<div class="cards">
{cards}
</div>
<footer class="src"><em>MVP — {n_articles} статьи. Полная таксономия: 48 статей в 10 разделах.</em></footer>
</main>
</body>
</html>
"""

CATEGORY_TITLES = {
    "battery-health": "Батарея и охлаждение",
    "doors-access": "Двери и доступ",
    "tires-wheels": "Шины и диски",
}

# Map article slug → topic spec from topics.yaml (mini-mirror to avoid yaml dep)
TOPIC_META = {
    "antifreeze": {"category": "battery-health"},
    "doors": {"category": "doors-access"},
    "tire-pressure": {"category": "tires-wheels"},
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
    # ⚠️ at start of <li> → wrap with .warning class
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
            # lead = first non-empty italic line after title
            for j in range(i + 1, min(i + 6, len(lines))):
                stripped = lines[j].strip()
                if stripped.startswith("*") and stripped.endswith("*") and len(stripped) > 2:
                    lead = stripped[1:-1].strip()
                    break
            break

    # Render full markdown (including title + lead)
    html_body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br"],
        output_format="html5",
    )
    # Promote the lead paragraph to .lead class
    if lead:
        html_body = html_body.replace(
            f"<p><em>{lead}</em></p>",
            f'<p class="lead">{lead}</p>',
            1,
        )
    # Wrap source footer (the line after final ---)
    html_body = replace_inline_badges(html_body)
    return title, lead, html_body


def build():
    PORTAL_DIR.mkdir(exist_ok=True)
    articles = []
    for slug, meta in TOPIC_META.items():
        md_path = ARTICLES_DIR / f"{slug}.md"
        if not md_path.exists():
            print(f"  [skip] {slug}: missing {md_path}")
            continue
        title, lead, body = parse_article(md_path)
        category_title = CATEGORY_TITLES.get(meta["category"], meta["category"])
        page_html = PAGE_TEMPLATE.format(
            title=title,
            css=CSS,
            category=category_title,
            body=body,
        )
        out_path = PORTAL_DIR / f"{slug}.html"
        out_path.write_text(page_html, encoding="utf-8")
        articles.append({
            "slug": slug,
            "title": title,
            "lead": lead,
            "category": category_title,
            "out": out_path,
        })
        print(f"  [ok] {slug}: {len(body)} chars → {out_path.name}")

    # Build index
    cards_html = "\n".join(
        f'<a class="card" href="{a["slug"]}.html">'
        f'<h2>{a["title"]}</h2>'
        f'<p>{a["lead"]}</p>'
        f'</a>'
        for a in articles
    )
    # Compute total source messages from articles' first numbers
    # Quick parse: find "из NNNN сообщений" in each article
    total = 0
    for a in articles:
        md = (ARTICLES_DIR / f"{a['slug']}.md").read_text()
        m = re.search(r"из (\d[\d\s]+) сообщений", md)
        if m:
            total += int(m.group(1).replace(" ", ""))
    index_html = INDEX_TEMPLATE.format(
        css=CSS,
        cards=cards_html,
        total_msgs=f"{total:,}".replace(",", " ") if total else "5 000",
        n_articles=len(articles),
    )
    (PORTAL_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"  [ok] index.html → {len(articles)} cards")


if __name__ == "__main__":
    build()
    print(f"\nPortal built. Preview:\n  cd {PORTAL_DIR}\n  python -m http.server 8000\nThen open http://localhost:8000/")
