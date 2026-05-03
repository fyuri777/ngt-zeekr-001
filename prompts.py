"""LLM prompts for the Zeekr 001 article synthesis pipeline.

All prompts instruct the model to write Russian inside JSON values / final article
because the source data is Russian and so is the target audience. The structural
instructions and field names stay English so the schema is easy to parse and grep.
"""

EXTRACT_PROMPT = """Ты анализируешь сообщения из чата владельцев Zeekr 001.

ЗАДАЧА: вытащить из этого батча сообщений структурированные находки по теме «{ru_title}».

ОЖИДАЕМЫЕ ПОДТЕМЫ:
{expected_themes}

КЛЮЧЕВЫЕ СЛОВА (для ориентира): {keywords}

Сообщения сгруппированы в треды (родитель + ответы). Внутри треда контекст последовательный.

Верни СТРОГО валидный JSON по этой схеме (никакого текста до или после JSON, никаких markdown-кодоблоков):

{{
  "key_questions": [
    {{"q": "вопрос как формулирует владелец", "frequency": "rare|some|frequent"}}
  ],
  "key_answers": [
    {{
      "q_ref": "ровно та же строка что и в key_questions выше, иначе пропусти",
      "answer": "сжатый ответ на 1-3 предложения, по сути, без лирики",
      "confidence": "low|med|high",
      "anchor_msg_ids": [{{"id": <int>, "channel": "<channel_name>"}}]
    }}
  ],
  "controversies": [
    {{
      "topic": "формулировка спорного вопроса в одну строку",
      "camp_a": {{"position": "позиция лагеря A", "evidence": "что они приводят в обоснование"}},
      "camp_b": {{"position": "позиция лагеря B", "evidence": "что они приводят в обоснование"}}
    }}
  ],
  "warnings": [
    {{"warning": "конкретное предупреждение/ловушка", "why": "почему это важно"}}
  ],
  "specific_data": [
    {{"fact": "конкретный факт с числом/моделью/ценой/литражом и т.п.", "context": "когда это применимо"}}
  ]
}}

ПРАВИЛА:
- Пиши значения JSON-полей ПО-РУССКИ (это контент-слой, не структура).
- Не цитируй сообщения дословно, синтезируй.
- Не выдумывай. Если в батче нет данных по подтеме — не добавляй пустых записей.
- anchor_msg_ids: указывай 1-3 наиболее показательных сообщения, к которым стоит привязать ответ.
- frequency: rare = 1-2 упоминания, some = 3-5, frequent = 6+.
- confidence: high = несколько независимых владельцев + конкретика; med = один уверенный ответ или мнение мастера; low = догадка/одиночное мнение.
- Если поле должно быть пустым — верни пустой массив, не выдумывай заполнение.

БАТЧ:
{batch_text}
"""

MERGE_PROMPT = """Ты сводишь несколько батчей находок по теме «{ru_title}» в один консолидированный набор.

Подтемы для ориентира:
{expected_themes}

Тебе на вход поданы N JSON-батчей (массив объектов EXTRACT-схемы). Твоя задача:
1. Дедуплицировать вопросы и ответы, объединить близкие формулировки.
2. Сложить frequency: если один и тот же вопрос встречается в 3+ батчах — это frequent.
3. Поднять confidence у ответов, подтверждённых в нескольких батчах.
4. Усилить controversies: оставить только те, где обе стороны действительно представлены, отбросить мнимые споры.
5. Выбрать ОДИН best_anchor: самое показательное сообщение со всего корпуса (как правило — длинный пост с конкретикой или итоговый вывод обсуждения).

Верни СТРОГО валидный JSON (никакого markdown):

{{
  "key_questions": [{{"q": "...", "frequency": "rare|some|frequent"}}],
  "key_answers": [{{"q_ref": "...", "answer": "...", "confidence": "low|med|high", "anchor_msg_ids": [{{"id": <int>, "channel": "..."}}]}}],
  "controversies": [{{"topic": "...", "camp_a": {{"position": "...", "evidence": "..."}}, "camp_b": {{"position": "...", "evidence": "..."}}}}],
  "warnings": [{{"warning": "...", "why": "..."}}],
  "specific_data": [{{"fact": "...", "context": "..."}}],
  "best_anchor": {{"msg_id": <int>, "channel": "<channel_name>", "why": "почему именно это сообщение лучший якорь"}}
}}

Контент по-русски, структура английская.

БАТЧИ:
{batches_json}
"""

COMPOSE_PROMPT = """Ты пишешь статью на русском для портала знаний владельцев Zeekr 001.

Тема: «{ru_title}» (категория: {category}).
Период данных: {date_min_human} — {date_max_human}.
Корпус: {total_messages} сообщений из {total_threads} тредов в темах: {topic_titles_joined}.

ИСХОДНЫЕ ДАННЫЕ (консолидированные находки):
{merged_json}

ТРЕБОВАНИЯ К СТАТЬЕ:
- Язык: русский.
- Длина: 1500-3500 слов.
- Структура: 5-8 H2-секций (включая «Спорные моменты» и «Предупреждения», если они есть).
- Data-first: конкретные числа, диапазоны, модели, цены, литражи. Никакой воды и общих фраз.
- НЕ цитируй сообщения дословно. Синтезируй.
- Спорные вопросы — оформляй как «два лагеря», обе стороны честно.
- Где уместно, ставь evidence-бейджи прямо в тексте: 📌 OFFICIAL (из мануала / FAQ), 👥 CONSENSUS (10+ владельцев согласны), 🔥 DEBATED (спор), ⚠️ STALE (старый совет, может быть неактуален), 🆕 RECENT (последние 90 дней).
- Без прямых ссылок на t.me внутри тела статьи — единственный якорный пост указывается в футере.

ФОРМАТ ВЫХОДА (строго этот скелет, верни только Markdown без обёртки):

# {ru_title}

*<Лид-подзаголовок: одно предложение по-русски, что в статье и почему ей можно верить — например, «Обзор практики владельцев Zeekr 001 за {date_min_human} — {date_max_human}: что говорят {total_messages}+ сообщений о ...».>*

## <H2 секция 1>
<Текст секции — конкретика, числа, без цитат>

## <H2 секция 2>
...

## <H2 секция N — всего 5-8>
...

## Спорные моменты
<Если есть controversies — перечисли каждый как:>

### <topic>
🔥 ОБСУЖДАЕТСЯ

**Лагерь A:** <position_a>
<evidence_a — 1-3 предложения>

**Лагерь B:** <position_b>
<evidence_b — 1-3 предложения>

## Предупреждения
- ⚠️ <warning 1>
- ⚠️ <warning 2>

---
*Статья собрана из {total_messages} сообщений тем «{topic_titles_joined}» за период {date_min_human} — {date_max_human}.*

*Якорный пост: [t.me/{anchor_channel}/{anchor_msg_id}](https://t.me/{anchor_channel}/{anchor_msg_id})*

ЖЁСТКИЕ ПРАВИЛА (повторяю для модели):
Do NOT quote messages verbatim. Synthesize. Use specific numbers and ranges. Frame controversies as two camps. Use Russian throughout the article. Article length: 1500-3500 words. 5-8 H2 sections.
"""
