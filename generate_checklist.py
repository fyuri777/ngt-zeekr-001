"""Generate Zeekr 001 used-car purchase checklist.

Inputs:
  - Voyah Dream checklist (.docx) as structural template
  - Existing Zeekr articles (antifreeze, doors, tire-pressure, master-account)
  - buying-used merged.json (if available) for buying-specific facts

Single Claude call: adapt the Voyah scaffold to Zeekr 001 specifics —
remove items that don't apply (sliding doors, 3rd row), modify items where
Zeekr differs, ADD Zeekr-only items (ZDS, antifreeze leak risk, MA transfer,
дорест vs рест identification, electronic flush handles).

Output: articles/buying-used-checklist.md
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
ARTICLES_DIR = ROOT / "articles"
CACHE_DIR = ROOT / "cache"
VOYAH_DOCX = (
    ROOT.parent / "orchestrator" / ".runs" / "tg-knowledge-portal-2026-05" / "checklist.docx"
)
OUTPUT = ARTICLES_DIR / "buying-used-checklist.md"


def extract_docx_text(path: Path) -> str:
    """Pull plain text out of a .docx (Word 2007+) without external deps."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"<w:tab[^/]*/>", "\t", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_zeekr_context() -> str:
    """Concatenate already-built Zeekr articles as factual context."""
    chunks = []
    for slug in ("antifreeze", "doors", "tire-pressure", "master-account"):
        p = ARTICLES_DIR / f"{slug}.md"
        if p.exists():
            chunks.append(f"### Article: {slug}\n\n{p.read_text(encoding='utf-8')}\n")
    # buying-used merged findings if available
    bu = CACHE_DIR / "buying-used" / "03_merged.json"
    if bu.exists():
        try:
            d = json.loads(bu.read_text(encoding="utf-8"))
            chunks.append("### Buying-used merged findings (JSON)\n\n```json\n"
                          + json.dumps(d, ensure_ascii=False, indent=2)[:30000]
                          + "\n```\n")
        except Exception as e:
            print(f"  [warn] could not read buying-used merged.json: {e}")
    return "\n---\n".join(chunks)


PROMPT = """ВАЖНО: твой ответ ДОЛЖЕН БЫТЬ финальный markdown-документ чеклиста целиком, без преамбулы и без пост-описания. НЕ пиши «я создал файл», НЕ перечисляй что добавил/удалил, НЕ описывай свою работу. Просто верни готовый markdown-чеклист от первого `# ` заголовка до последнего символа.

Ты адаптируешь чеклист предпокупочного осмотра автомобиля.

ИСХОДНЫЙ ЧЕКЛИСТ — для Voyah Dream (китайский 3-рядный кроссовер с раздвижными задними дверями, гибрид). НЕ копируй слепо: Zeekr 001 — это седан, без раздвижных дверей, без 3-го ряда, чисто электрический, с пневмоподвеской, с электронными утопленными ручками дверей.

ZEEKR-СПЕЦИФИКА (из готовых статей и обсуждений сообщества) — встроенный контекст внизу. Используй его, чтобы:
1. ДОБАВИТЬ пункты, которых нет у Voyah, но критичны для Zeekr 001:
   - Антифриз: проверить уровень в бачке (на ранних доресте до января 2023 — ДВА бачка, второй скрыт под пластиком), цвет (синий vs розовый — связан с риском протечки в батарею 2024 г.р.), фото с предпродажным замером pH/EC, запись о сервисном бюллетене QBS/QBD
   - ВВБ: год выпуска батареи, тип (86 NMC дорест / 95 LFP / 100 NMC рест), история по гарантии (особенно если рест 2024 г.р. — повышенный риск протечки антифриза)
   - Электронные ручки дверей: проверить работу всех 4-х на холоде, тест автоматического приоткрытия, отсутствие запотевания/отклеивания датчиков (типичная проблема дореста)
   - Прошивка: версия (5.x на дорест, 6.x на рест), наличие XMETA/Infohub/GMC русификации, кто её делал, гарантия на русификацию
   - Мастер-аккаунт: КТО владелец eSender-номера, есть ли передача, доступен ли WeChat владельца, какой телефон привязан как RU SIM
   - TPMS: датчики дорест и рест НЕ совместимы, спросить артикул (8889081697 дорест / 8894215959 рест), наличие второго комплекта (зимний)
   - Пневмоподвеска: режим Jack для замены колёс, проверка работы в трёх режимах высоты, отсутствие просадки за ночь, состояние компрессора (на дорест без фильтра — забирает пыль)
   - Сервисный режим (ZDS): спросить, выполнялся ли сервисный бюллетень QBS/QBD по антифризу, есть ли запись о прокачке контура охлаждения через ZDS

2. УДАЛИТЬ пункты, которых нет на Zeekr 001:
   - Раздвижные задние двери (у Zeekr 001 классические распашные)
   - Сиденья третьего ряда
   - ДВС / гибрид (Zeekr 001 — чистый EV, нет моторного масла, нет ДВС-проверок; есть только редукторное масло переднего/заднего моста, тормозная жидкость, антифриз контура батареи)

3. АДАПТИРОВАТЬ пункты, где Zeekr отличается от Voyah:
   - Зарядка: AC порт + DC порт расположение, синяя/зелёная индикация лючка, GBT vs CCS2 совместимость
   - Зарядное оборудование: спросить идёт ли в комплекте оригинал, артикул
   - Защитная плёнка: на Zeekr 001 особенно проверить области у электронных ручек (могут отклеиваться от тепла bluetooth-антенны)
   - 12В АКБ: расположение в багажнике (правая ниша) — стандарт; ВАЖНО: проверить динамику напряжения за ночь, на Zeekr склонность к разрядке от OBD-донглов и Pandora

ФОРМАТ ВЫХОДА — строго Markdown:

# Чеклист предпокупочного осмотра Zeekr 001

*Адаптирован под Zeekr 001 (седан, EV, пневма, дорест/рест) на основе универсального чеклиста + опыта клуба владельцев. Использовать с фото/видеофиксацией каждого дефекта.*

## Перед началом
- [ ] пункт
- [ ] пункт
...

## Документы и история
- [ ] пункт
...

## Кузов и ЛКП
...

## Остекление и оптика
...

## Колёса, шины, диски
...

## Двери (электронные ручки) — критично для Zeekr 001
...

## Подкапотное (нет ДВС, есть редукторы и контуры охлаждения)
...

## 12В АКБ
...

## Зарядка ВВБ — AC и DC
...

## Высоковольтная батарея и антифриз — критическая зона риска
...

## Пневмоподвеска
...

## Прошивка и русификация
...

## Мастер-аккаунт и связь
...

## Салон и комфорт
...

## Тест-драйв
...

## Финальная проверка через сервисный сканер ZDS
...

---
*Чеклист построен на универсальной основе для Chinese EV + клубный опыт Zeekr 001 (август 2024 — май 2026). Каждый пункт с фото-фиксацией. Особо рисковые зоны — выделены жирным.*

ВАЖНЫЕ ПРАВИЛА:
- Каждый пункт начинай с `- [ ] ` (пустой чекбокс).
- Жирным выделяй критические Zeekr-специфичные риски.
- Сохрани конкретные числа (артикулы, даты, цены).
- НЕ добавляй пунктов «спросить продавца» без конкретики — каждый вопрос должен быть проверяемым.
- Длина: 2500-4000 слов (это рабочий документ, должен быть исчерпывающим).
- Используй русский язык во всём документе.
- ОТВЕТ = ТОЛЬКО САМ ДОКУМЕНТ. Без преамбулы, без «вот что я сделал», без подведения итогов в конце. Начни с `# Чеклист предпокупочного осмотра Zeekr 001` и закончи финальной строкой документа.

ИСХОДНЫЙ ЧЕКЛИСТ VOYAH DREAM:
{voyah_text}

ZEEKR 001 КОНТЕКСТ (готовые статьи + находки):
{zeekr_context}
"""


def call_claude(prompt: str) -> str:
    """Call claude -p directly (skip claude-batch tmux wrapper).

    The wrapper adds a token-lifetime gate that flakes on big prompts.
    Direct invocation is simpler and reliable for a single one-shot call.
    Prompt is piped via stdin to avoid argv length issues.
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    last_err = ""
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["claude", "-p", "--model", "sonnet"],
                input=prompt,
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
            last_err = f"rc={r.returncode}, stderr={r.stderr[:500]}"
        except subprocess.TimeoutExpired as e:
            last_err = f"timeout {e.timeout}s"
        print(f"  [retry] checklist gen: {last_err}")
        time.sleep(2 ** attempt)
    raise RuntimeError(f"checklist gen failed: {last_err}")


def main():
    if not VOYAH_DOCX.exists():
        sys.exit(f"Voyah checklist not found at {VOYAH_DOCX}")
    voyah = extract_docx_text(VOYAH_DOCX)
    print(f"  [src] Voyah checklist: {len(voyah)} chars")

    zeekr_context = load_zeekr_context()
    print(f"  [ctx] Zeekr context: {len(zeekr_context)} chars")

    prompt = PROMPT.format(voyah_text=voyah, zeekr_context=zeekr_context)
    print(f"  [prompt] total: {len(prompt)} chars")

    t0 = time.monotonic()
    md = call_claude(prompt).strip()
    dt = time.monotonic() - t0

    # Strip accidental code-fence wrapper
    md = re.sub(r"^```(?:markdown|md)?\s*\n", "", md)
    md = re.sub(r"\n```\s*$", "", md)

    OUTPUT.write_text(md, encoding="utf-8")
    words = len(md.split())
    print(f"  [done] {OUTPUT.name}: {words} words in {dt:.1f}s")


if __name__ == "__main__":
    main()
