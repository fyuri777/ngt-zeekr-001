"""Zeekr 001 article synthesis pipeline.

Stages: GATHER (SQLite) -> BATCH-EXTRACT (Sonnet) -> MERGE (Sonnet) ->
COMPOSE (Sonnet) -> REPORT.

CLI:
    python synthesize.py --topic antifreeze
    python synthesize.py --all
    python synthesize.py --all --rebuild

All API calls are cached on disk under cache/<slug>/<stage>/<batch_id>.json
and reused on rerun unless --rebuild is passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prompts import (
    COMPOSE_PROMPT,
    EXTRACT_PROMPT_PREFIX,
    EXTRACT_PROMPT_SUFFIX_TEMPLATE,
    MERGE_PROMPT_PREFIX,
    MERGE_PROMPT_SUFFIX_TEMPLATE,
)

# -----------------------------------------------------------------------------
# Paths and constants
# -----------------------------------------------------------------------------

ROOT = Path(__file__).parent
DB_PATH = ROOT / "zeekr.db"
CACHE_DIR = ROOT / "cache"
ARTICLES_DIR = ROOT / "articles"
TOPICS_YAML = ROOT / "topics.yaml"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY_PATH = Path.home() / ".openrouter" / "api_key"
HTTP_REFERER = "https://github.com/fyuri777/ngt-zeekr-001"

# Fallback chain. Sonnet 4.6 is not available on OpenRouter as of 2026-05.
# Verified: 4.5 works (model resolves to anthropic/claude-4.5-sonnet-20250929).
MODEL_FALLBACKS = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-3.7-sonnet",
]

# Pricing per 1M tokens — keep in sync with MODEL_BENCHMARKS.md.
PRICING = {
    "anthropic/claude-sonnet-4.6": (3.0, 15.0),
    "anthropic/claude-sonnet-4.5": (3.0, 15.0),
    "anthropic/claude-sonnet-4":   (3.0, 15.0),
    "anthropic/claude-3.7-sonnet": (3.0, 15.0),
}

# Batch size in raw text characters. ~4 chars/token for Cyrillic on average,
# so 50k chars ~= 12-16k input tokens — Sonnet 4.6 has 1M context window, so
# this is comfortably safe and roughly halves the batch count vs the old 25k.
BATCH_CHAR_BUDGET = 50_000

# Parallel concurrency for claude-batch native batch mode (extract stage only).
# Empirically 5 keeps tmux/token pressure tame; raising it usually triggers
# the claude-batch token-margin warnings and timeouts.
EXTRACT_PARALLEL = 5

RU_MONTHS = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
    7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}

# -----------------------------------------------------------------------------
# Tiny YAML reader for our fixed-shape topics.yaml.
# We control the file format, so we avoid pulling in PyYAML as a dependency.
# Supports: 2-space indent, scalars, lists with `[a, b, c]` or `- item` blocks,
# integer values for numeric scalars. No anchors, no nested mappings beyond 3
# levels. If we ever need richer YAML, swap to PyYAML.
# -----------------------------------------------------------------------------

def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_scalar(s: str) -> Any:
    s = s.strip()
    if not s:
        return ""
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip() for p in _split_top_commas(inner)]
        return [_parse_scalar(p) for p in parts]
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return _strip_quotes(s)


def _split_top_commas(s: str) -> list[str]:
    out, buf, depth, in_str, str_ch = [], [], 0, False, ""
    for ch in s:
        if in_str:
            buf.append(ch)
            if ch == str_ch:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str, str_ch = True, ch
            buf.append(ch)
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def load_topics_yaml(path: Path) -> dict[str, dict]:
    """Parse topics.yaml. Returns {slug: spec_dict}."""
    text = path.read_text(encoding="utf-8")
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Strip comments and blank lines
    cleaned = []
    for ln in lines:
        # Preserve `#` inside quoted strings — we never use that here, so simple split is fine
        idx = ln.find("#")
        if idx >= 0 and ln[:idx].strip() == "":
            continue
        cleaned.append(ln)

    # We expect a top-level `topics:` key.
    root: dict[str, Any] = {}
    i = 0
    while i < len(cleaned):
        ln = cleaned[i]
        if ln.startswith("topics:"):
            i += 1
            break
        i += 1

    topics: dict[str, dict] = {}
    current_slug: str | None = None
    current_spec: dict[str, Any] = {}
    current_list_key: str | None = None

    def flush_current():
        if current_slug is not None:
            topics[current_slug] = dict(current_spec)

    while i < len(cleaned):
        ln = cleaned[i]
        if not ln.strip():
            i += 1
            continue
        # New topic at 2-space indent (e.g. "  antifreeze:")
        m = re.match(r"^  ([a-zA-Z0-9_\-]+):\s*$", ln)
        if m:
            flush_current()
            current_slug = m.group(1)
            current_spec = {}
            current_list_key = None
            i += 1
            continue
        # Field at 4-space indent: "    key: value" or "    key:" (for lists)
        m = re.match(r"^    ([a-zA-Z0-9_]+):\s*(.*)$", ln)
        if m and current_slug is not None:
            key, val = m.group(1), m.group(2)
            if val == "":
                current_list_key = key
                current_spec[key] = []
            else:
                current_list_key = None
                current_spec[key] = _parse_scalar(val)
            i += 1
            continue
        # List item at 6-space indent: "      - foo"
        m = re.match(r"^      - (.*)$", ln)
        if m and current_slug is not None and current_list_key is not None:
            current_spec[current_list_key].append(_parse_scalar(m.group(1)))
            i += 1
            continue
        # Unknown line — skip defensively.
        i += 1

    flush_current()
    return topics


# -----------------------------------------------------------------------------
# DB access (read-only)
# -----------------------------------------------------------------------------

def open_db_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


# -----------------------------------------------------------------------------
# Stage 1: GATHER
# -----------------------------------------------------------------------------

@dataclass
class Message:
    id: int
    channel_id: int
    channel_name: str
    date: str
    text: str
    from_name: str | None
    reply_to_msg_id: int | None
    topic_id: int | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "date": self.date,
            "text": self.text,
            "from_name": self.from_name,
            "reply_to_msg_id": self.reply_to_msg_id,
            "topic_id": self.topic_id,
        }


def _row_to_msg(row) -> Message:
    return Message(
        id=row[0],
        channel_id=row[1],
        channel_name=row[2],
        date=row[3],
        text=row[4] or "",
        from_name=row[5],
        reply_to_msg_id=row[6],
        topic_id=row[7],
    )


MSG_COLS = "id, channel_id, channel_name, date, text, from_name, reply_to_msg_id, topic_id"


def _topic_titles(conn: sqlite3.Connection, topic_ids: list[int]) -> list[str]:
    placeholders = ",".join(["?"] * len(topic_ids))
    rows = conn.execute(
        f"SELECT id, title FROM topics WHERE id IN ({placeholders})", topic_ids
    ).fetchall()
    by_id = {r[0]: r[1] for r in rows}
    return [by_id.get(tid, str(tid)) for tid in topic_ids]


def gather_topic(conn: sqlite3.Connection, slug: str, spec: dict) -> dict:
    """
    Gather candidate messages for a topic.

    Strategy (decided per brief):
      - Dedicated 001 topics (129577 «001 Дорест», 489048 «001 Рест») are extremely
        broad — we MUST keyword-filter them, otherwise every topic explodes to 8-9k
        messages and the budget. So for these two topic_ids we require keyword match.
      - More-specific topics in the per-topic list (e.g. 129579 «Обслуживание и ремонт»,
        129585 «Шины и диски») are narrow enough that we accept ALL their messages.
      - Length filter: 40 <= len(text) <= 2000 (drops "ок", "спс", and link spam).
    """
    BROAD_TOPIC_IDS = {129577, 489048, 730610, 129581, 180635}

    topic_ids: list[int] = list(spec["topic_ids"])
    keywords: list[str] = list(spec["keywords"])

    broad = [t for t in topic_ids if t in BROAD_TOPIC_IDS]
    narrow = [t for t in topic_ids if t not in BROAD_TOPIC_IDS]

    seeds: dict[tuple[int, int], Message] = {}

    if broad and keywords:
        kw_clauses = " OR ".join(["LOWER(text) LIKE ?"] * len(keywords))
        params: list[Any] = [f"%{kw.lower()}%" for kw in keywords]
        placeholders = ",".join(["?"] * len(broad))
        sql = (
            f"SELECT {MSG_COLS} FROM messages "
            f"WHERE topic_id IN ({placeholders}) "
            f"AND length(text) BETWEEN 40 AND 2000 "
            f"AND ({kw_clauses})"
        )
        rows = conn.execute(sql, list(broad) + params).fetchall()
        for r in rows:
            m = _row_to_msg(r)
            seeds[(m.id, m.channel_id)] = m

    if narrow:
        placeholders = ",".join(["?"] * len(narrow))
        sql = (
            f"SELECT {MSG_COLS} FROM messages "
            f"WHERE topic_id IN ({placeholders}) "
            f"AND length(text) BETWEEN 40 AND 2000"
        )
        rows = conn.execute(sql, list(narrow)).fetchall()
        for r in rows:
            m = _row_to_msg(r)
            seeds[(m.id, m.channel_id)] = m

    print(f"  [gather] {slug}: {len(seeds)} seed messages")

    # Reconstruct depth-1 reply context: parents + direct children.
    enriched: dict[tuple[int, int], Message] = dict(seeds)
    for key, msg in list(seeds.items()):
        # Parent (depth 1 up)
        if msg.reply_to_msg_id:
            row = conn.execute(
                f"SELECT {MSG_COLS} FROM messages "
                f"WHERE id=? AND channel_name=? AND length(text) BETWEEN 40 AND 2000",
                (msg.reply_to_msg_id, msg.channel_name),
            ).fetchone()
            if row:
                pm = _row_to_msg(row)
                enriched[(pm.id, pm.channel_id)] = pm
        # Direct children (depth 1 down)
        rows = conn.execute(
            f"SELECT {MSG_COLS} FROM messages "
            f"WHERE reply_to_msg_id=? AND channel_name=? "
            f"AND length(text) BETWEEN 40 AND 2000",
            (msg.id, msg.channel_name),
        ).fetchall()
        for r in rows:
            cm = _row_to_msg(r)
            enriched[(cm.id, cm.channel_id)] = cm

    # Group into threads by (channel_name, root). Root is reply_to_msg_id of seed if
    # present in our set, else the message itself.
    thread_for: dict[tuple[int, int], tuple[str, int]] = {}
    for key, m in enriched.items():
        root_id = m.reply_to_msg_id if (m.reply_to_msg_id and any(
            k[0] == m.reply_to_msg_id and enriched[k].channel_name == m.channel_name
            for k in enriched
        )) else m.id
        thread_for[key] = (m.channel_name, root_id)

    threads: dict[tuple[str, int], list[Message]] = {}
    for key, m in enriched.items():
        threads.setdefault(thread_for[key], []).append(m)

    # Sort messages inside thread by date asc; threads by latest message desc.
    thread_list = []
    for tkey, msgs in threads.items():
        msgs_sorted = sorted(msgs, key=lambda x: x.date or "")
        thread_list.append((tkey, msgs_sorted))
    thread_list.sort(
        key=lambda pair: max((m.date or "") for m in pair[1]),
        reverse=True,
    )

    all_msgs = [m for _, msgs in thread_list for m in msgs]
    if not all_msgs:
        return {
            "stats": {"total_messages": 0, "total_threads": 0, "date_min": None, "date_max": None},
            "threads": [],
            "topic_titles": _topic_titles(conn, topic_ids),
        }

    dates = [m.date for m in all_msgs if m.date]
    stats = {
        "total_messages": len(all_msgs),
        "total_threads": len(thread_list),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
    }

    threads_out = []
    for (channel_name, root_id), msgs in thread_list:
        threads_out.append({
            "thread_id": f"{channel_name}/{root_id}",
            "messages": [m.to_dict() for m in msgs],
        })

    return {
        "stats": stats,
        "threads": threads_out,
        "topic_titles": _topic_titles(conn, topic_ids),
    }


# -----------------------------------------------------------------------------
# OpenRouter client (stdlib only, with retry and disk cache)
# -----------------------------------------------------------------------------

@dataclass
class CallStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    calls: int = 0


@dataclass
class TimingStats:
    """Per-stage wall-clock for a single topic run. All values in seconds."""
    gather: float = 0.0
    extract: float = 0.0
    extract_batches: int = 0   # batches actually processed (not cache-hits)
    merge: float = 0.0
    compose: float = 0.0
    total: float = 0.0


def _read_api_key() -> str:
    if not OPENROUTER_KEY_PATH.exists():
        sys.exit(f"OpenRouter key not found at {OPENROUTER_KEY_PATH}")
    return OPENROUTER_KEY_PATH.read_text().strip()


def claude_call(
    prompt: str,
    *,
    response_format_json: bool,  # noqa: ARG001  (kept for signature compat)
    max_tokens: int,             # noqa: ARG001  (kept for signature compat)
    stats: CallStats,
    label: str,
) -> str:
    """Call Claude Sonnet 4.6 via claude-batch (Claude Code session, no API cost).

    claude-batch wraps `claude -p` in a tmux-isolated session. We must unset
    CLAUDECODE / CLAUDE_CODE_ENTRYPOINT so the inner `claude` does not refuse
    to run as a nested session.
    """
    import subprocess

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    last_err = ""
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["claude-batch", "-p", prompt, "--model", "sonnet"],
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
            )
            if result.returncode == 0 and result.stdout.strip():
                stats.calls += 1
                stats.model_used = "claude-sonnet-4.6"
                return result.stdout
            last_err = f"rc={result.returncode}, stderr={result.stderr[:300]}"
            print(f"  [retry] {label}: {last_err} (attempt {attempt+1}/3)")
            time.sleep(2 ** attempt)
        except subprocess.TimeoutExpired as e:
            last_err = f"timeout after {e.timeout}s"
            print(f"  [retry] {label}: {last_err}")
            time.sleep(2 ** attempt)

    raise RuntimeError(f"claude-batch failed for {label}: {last_err}")


# Alias for backward compatibility with existing call sites in this file.
openrouter_call = claude_call


# -----------------------------------------------------------------------------
# Stage 2: BATCH-EXTRACT
# -----------------------------------------------------------------------------

def _format_batch_text(threads: list[dict]) -> str:
    """Render threads as plain text for the LLM. Compact but unambiguous."""
    out = []
    for th in threads:
        out.append(f"=== THREAD {th['thread_id']} ===")
        for m in th["messages"]:
            who = m.get("from_name") or "anon"
            date = (m.get("date") or "")[:10]
            mid = m["id"]
            ch = m["channel_name"]
            text = (m.get("text") or "").strip().replace("\n", " ")
            out.append(f"[id={mid} ch={ch} {date} {who}] {text}")
        out.append("")
    return "\n".join(out)


def _build_batches(threads: list[dict], char_budget: int) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_size = 0
    for th in threads:
        # Per-thread approximate size.
        th_size = sum(len(m.get("text") or "") for m in th["messages"]) + 80 * len(th["messages"])
        if current and current_size + th_size > char_budget:
            batches.append(current)
            current = []
            current_size = 0
        current.append(th)
        current_size += th_size
    if current:
        batches.append(current)
    return batches


def _strip_json_fence(s: str) -> str:
    """Some models wrap JSON in ```json ... ``` despite instructions."""
    s = s.strip()
    if s.startswith("```"):
        # remove first fence line
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _extract_json(raw: str, debug_path: Path) -> dict | None:
    cleaned = _strip_json_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to locate first { ... last }
        i = cleaned.find("{")
        j = cleaned.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(cleaned[i:j+1])
            except json.JSONDecodeError:
                pass
    debug_path.write_text(raw, encoding="utf-8")
    print(f"  [warn] JSON parse failed, raw saved to {debug_path}")
    return None


def _build_extract_prompt(spec: dict, batch: list[dict]) -> str:
    """PREFIX is identical across calls (cache-hit eligible). Only SUFFIX varies."""
    suffix = EXTRACT_PROMPT_SUFFIX_TEMPLATE.format(
        ru_title=spec["ru_title"],
        expected_themes="\n".join(f"- {t}" for t in spec["expected_themes"]),
        keywords=", ".join(spec["keywords"]),
        batch_text=_format_batch_text(batch),
    )
    return EXTRACT_PROMPT_PREFIX + suffix


def _extract_parallel(
    pending: list[tuple[int, str]],
    cache_dir: Path,
    slug: str,
) -> tuple[bool, str]:
    """Run pending extract batches in parallel via ThreadPoolExecutor.

    Each worker invokes `claude-batch -p ...` in drop-in mode (which is
    reliable, unlike the `claude-batch batch` mode that flakes on the
    token-lifetime gate when run on multi-prompt fan-outs). Writes per-batch
    JSON into cache_dir / 02_batches / <idx:03d>.json.

    Returns (success, error_message). On failure the caller should fall
    back to the sequential loop.
    """
    import concurrent.futures
    import subprocess

    if not pending:
        return True, ""

    batches_dir = cache_dir / "02_batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    print(f"  [extract] {slug}: parallel pool size={EXTRACT_PARALLEL}, {len(pending)} batches")

    def _one(idx: int, prompt: str) -> tuple[int, str | None]:
        """Run one batch. Returns (idx, raw_output_or_None)."""
        for attempt in range(3):
            try:
                r = subprocess.run(
                    ["claude-batch", "-p", prompt, "--model", "sonnet"],
                    env=env, capture_output=True, text=True, timeout=900,
                )
                if r.returncode == 0 and r.stdout.strip():
                    return idx, r.stdout
                err = f"rc={r.returncode}, stderr={r.stderr[:200]}"
            except subprocess.TimeoutExpired as e:
                err = f"timeout {e.timeout}s"
            print(f"  [retry] extract batch {idx}: {err} (attempt {attempt + 1}/3)")
            time.sleep(2 ** attempt)
        return idx, None

    missing: list[int] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=EXTRACT_PARALLEL) as pool:
        futures = [pool.submit(_one, idx, prompt) for idx, prompt in pending]
        for fut in concurrent.futures.as_completed(futures):
            idx, raw = fut.result()
            if raw is None:
                missing.append(idx)
                continue
            debug_path = batches_dir / f"{idx:03d}.raw.txt"
            parsed = _extract_json(raw, debug_path)
            if parsed is None:
                parsed = {
                    "key_questions": [], "key_answers": [], "controversies": [],
                    "warnings": [], "specific_data": [],
                    "_parse_error": True,
                }
            (batches_dir / f"{idx:03d}.json").write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    if missing:
        return False, f"parallel extract missing {len(missing)}/{len(pending)}: {missing[:5]}..."
    return True, ""


def stage_extract(
    slug: str,
    spec: dict,
    gather: dict,
    cache_dir: Path,
    stats: CallStats,
    rebuild: bool,
) -> tuple[dict, int]:
    """Run EXTRACT stage. Returns (aggregate, batches_processed_this_run).

    batches_processed_this_run excludes cache-hits and is used to compute the
    avg-seconds-per-batch metric in the per-stage timing line.
    """
    batches_dir = cache_dir / "02_batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    batches = _build_batches(gather["threads"], BATCH_CHAR_BUDGET)
    print(f"  [extract] {slug}: {len(batches)} batches (char_budget={BATCH_CHAR_BUDGET})")

    # Identify which batches need fresh runs (preserve cache-skip behaviour).
    pending: list[tuple[int, str]] = []
    for idx, batch in enumerate(batches):
        cache_path = batches_dir / f"{idx:03d}.json"
        if cache_path.exists() and not rebuild:
            continue
        prompt = _build_extract_prompt(spec, batch)
        pending.append((idx, prompt))

    n_processed = len(pending)
    cache_hits = len(batches) - n_processed
    if cache_hits:
        print(f"  [extract] {slug}: {cache_hits} cache-hit, {n_processed} to process")

    if pending:
        ok, err = _extract_parallel(pending, cache_dir, slug)
        if not ok:
            print(f"  [warn] parallel extract failed: {err}")
            print(f"  [warn] falling back to sequential claude_call loop")
            for idx, prompt in pending:
                cache_path = batches_dir / f"{idx:03d}.json"
                if cache_path.exists():  # parallel run produced this one already
                    continue
                raw = openrouter_call(
                    prompt,
                    response_format_json=True,
                    max_tokens=4096,
                    stats=stats,
                    label=f"extract:{slug}:{idx}",
                )
                debug_path = batches_dir / f"{idx:03d}.raw.txt"
                parsed = _extract_json(raw, debug_path)
                if parsed is None:
                    parsed = {
                        "key_questions": [], "key_answers": [], "controversies": [],
                        "warnings": [], "specific_data": [],
                        "_parse_error": True,
                    }
                cache_path.write_text(
                    json.dumps(parsed, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    # Read all per-batch JSON back in order to build the aggregate.
    extract_results: list[dict] = []
    for idx in range(len(batches)):
        cp = batches_dir / f"{idx:03d}.json"
        if cp.exists():
            extract_results.append(json.loads(cp.read_text(encoding="utf-8")))
        else:
            # Last-resort stub so downstream stages don't crash.
            extract_results.append({
                "key_questions": [], "key_answers": [], "controversies": [],
                "warnings": [], "specific_data": [],
                "_parse_error": True, "_missing": True,
            })

    aggregate = {"batches": extract_results, "n_batches": len(batches)}
    (cache_dir / "02_extract.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return aggregate, n_processed


# -----------------------------------------------------------------------------
# Stage 3: MERGE
# -----------------------------------------------------------------------------

def stage_merge(
    slug: str,
    spec: dict,
    extract: dict,
    cache_dir: Path,
    stats: CallStats,
    rebuild: bool,
) -> dict:
    out_path = cache_dir / "03_merged.json"
    if out_path.exists() and not rebuild:
        print(f"  [cached] merge {slug}")
        return json.loads(out_path.read_text(encoding="utf-8"))

    suffix = MERGE_PROMPT_SUFFIX_TEMPLATE.format(
        ru_title=spec["ru_title"],
        expected_themes="\n".join(f"- {t}" for t in spec["expected_themes"]),
        batches_json=json.dumps(extract["batches"], ensure_ascii=False),
    )
    prompt = MERGE_PROMPT_PREFIX + suffix
    raw = openrouter_call(
        prompt,
        response_format_json=True,
        max_tokens=8192,
        stats=stats,
        label=f"merge:{slug}",
    )
    parsed = _extract_json(raw, cache_dir / "03_merged.raw.txt")
    if parsed is None:
        # Fallback: synthesize a minimal merged blob from extract (best effort).
        parsed = {
            "key_questions": [], "key_answers": [], "controversies": [],
            "warnings": [], "specific_data": [],
            "best_anchor": None,
            "_parse_error": True,
        }
        for b in extract["batches"]:
            for k in ("key_questions", "key_answers", "controversies", "warnings", "specific_data"):
                parsed[k].extend(b.get(k, []) or [])
    out_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    return parsed


# -----------------------------------------------------------------------------
# Stage 4: COMPOSE
# -----------------------------------------------------------------------------

def _human_month(date_iso: str | None) -> str:
    if not date_iso:
        return "—"
    try:
        # date is ISO 'YYYY-MM-DD...' in our DB
        y = int(date_iso[:4])
        mo = int(date_iso[5:7])
        return f"{RU_MONTHS.get(mo, '?')} {y}"
    except Exception:
        return date_iso[:7]


def _pick_anchor(merged: dict, gather: dict) -> tuple[str, int]:
    """Return (channel_name, msg_id) for the article footer anchor."""
    ba = merged.get("best_anchor")
    if isinstance(ba, dict) and ba.get("msg_id") and ba.get("channel"):
        try:
            return str(ba["channel"]), int(ba["msg_id"])
        except (TypeError, ValueError):
            pass

    # Fallback: first anchor_msg_ids from merged answers
    for ans in merged.get("key_answers") or []:
        anchors = ans.get("anchor_msg_ids") or []
        if anchors:
            a = anchors[0]
            try:
                return str(a["channel"]), int(a["id"])
            except (KeyError, TypeError, ValueError):
                continue

    # Final fallback: first message in first thread
    for th in gather["threads"]:
        if th["messages"]:
            m = th["messages"][0]
            return m["channel_name"], int(m["id"])
    return "zeekrclub", 0


def stage_compose(
    slug: str,
    spec: dict,
    gather: dict,
    merged: dict,
    cache_dir: Path,
    stats: CallStats,
    rebuild: bool,
) -> str:
    out_path = ARTICLES_DIR / f"{slug}.md"
    cache_md = cache_dir / "04_compose.md"
    if out_path.exists() and not rebuild:
        print(f"  [cached] compose {slug}")
        return out_path.read_text(encoding="utf-8")

    anchor_channel, anchor_msg_id = _pick_anchor(merged, gather)
    stats_g = gather["stats"]
    topic_titles_joined = " | ".join(gather.get("topic_titles") or [])

    prompt = COMPOSE_PROMPT.format(
        ru_title=spec["ru_title"],
        category=spec["category"],
        date_min_human=_human_month(stats_g["date_min"]),
        date_max_human=_human_month(stats_g["date_max"]),
        total_messages=stats_g["total_messages"],
        total_threads=stats_g["total_threads"],
        topic_titles_joined=topic_titles_joined,
        merged_json=json.dumps(merged, ensure_ascii=False, indent=2),
        anchor_channel=anchor_channel,
        anchor_msg_id=anchor_msg_id,
    )
    raw = openrouter_call(
        prompt,
        response_format_json=False,
        max_tokens=8192,
        stats=stats,
        label=f"compose:{slug}",
    )
    md = raw.strip()
    # Strip accidental fences if the model wrapped in ```markdown ... ```
    if md.startswith("```"):
        md = re.sub(r"^```[a-zA-Z]*\n", "", md)
        if md.endswith("```"):
            md = md[:-3].rstrip()

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    cache_md.write_text(md, encoding="utf-8")
    return md


# -----------------------------------------------------------------------------
# Per-topic orchestrator
# -----------------------------------------------------------------------------

@dataclass
class TopicReport:
    slug: str
    messages: int = 0
    threads: int = 0
    batches: int = 0
    cost_usd: float = 0.0
    words: int = 0
    skipped_reason: str | None = None
    timing: TimingStats = field(default_factory=TimingStats)


def run_topic(slug: str, spec: dict, rebuild: bool) -> TopicReport:
    print(f"\n=== {slug} ===")
    cache_dir = CACHE_DIR / slug
    cache_dir.mkdir(parents=True, exist_ok=True)

    stats = CallStats()
    report = TopicReport(slug=slug)
    timing = report.timing

    t_topic_start = time.monotonic()

    # Stage 1: GATHER
    t0 = time.monotonic()
    gather_path = cache_dir / "01_gather.json"
    if gather_path.exists() and not rebuild:
        print(f"  [cached] gather {slug}")
        gather = json.loads(gather_path.read_text(encoding="utf-8"))
    else:
        with open_db_ro(DB_PATH) as conn:
            gather = gather_topic(conn, slug, spec)
        gather_path.write_text(json.dumps(gather, ensure_ascii=False, indent=2), encoding="utf-8")
    timing.gather = time.monotonic() - t0
    print(f"  [gather]    {slug}: {timing.gather:.1f}s")

    g_stats = gather["stats"]
    report.messages = g_stats["total_messages"]
    report.threads = g_stats["total_threads"]

    if g_stats["total_messages"] < spec.get("min_messages", 0):
        msg = f"only {g_stats['total_messages']} messages (< min_messages={spec.get('min_messages')})"
        print(f"  [skip] {slug}: {msg}")
        report.skipped_reason = msg
        timing.total = time.monotonic() - t_topic_start
        return report

    # Stage 2: EXTRACT
    t0 = time.monotonic()
    extract, n_processed = stage_extract(slug, spec, gather, cache_dir, stats, rebuild)
    timing.extract = time.monotonic() - t0
    timing.extract_batches = n_processed
    report.batches = extract["n_batches"]
    if n_processed:
        avg = timing.extract / n_processed
        print(f"  [extract]   {slug}: {n_processed} batches in {timing.extract:.1f}s "
              f"(avg {avg:.1f}s/batch)")
    else:
        print(f"  [extract]   {slug}: {timing.extract:.1f}s (all cache-hits)")

    # Stage 3: MERGE
    t0 = time.monotonic()
    merged = stage_merge(slug, spec, extract, cache_dir, stats, rebuild)
    timing.merge = time.monotonic() - t0
    print(f"  [merge]     {slug}: {timing.merge:.1f}s")

    # Stage 4: COMPOSE
    t0 = time.monotonic()
    md = stage_compose(slug, spec, gather, merged, cache_dir, stats, rebuild)
    timing.compose = time.monotonic() - t0
    print(f"  [compose]   {slug}: {timing.compose:.1f}s")

    timing.total = time.monotonic() - t_topic_start
    print(f"  [total]     {slug}: {timing.total:.1f}s")

    report.cost_usd = stats.cost_usd
    report.words = len(md.split())
    print(f"  [done] {slug}: {report.words} words, ${stats.cost_usd:.3f}, model={stats.model_used}")
    return report


# -----------------------------------------------------------------------------
# Stage 5: REPORT
# -----------------------------------------------------------------------------

def print_report(reports: list[TopicReport], wall_seconds: float):
    print("\n=== SUMMARY ===")
    header = (
        f"{'Topic':<20}{'Messages':>10}{'Threads':>10}{'Batches':>10}"
        f"{'Cost($)':>10}{'Words':>10}{'Time(s)':>10}"
    )
    print(header)
    print("-" * len(header))
    total_cost = 0.0
    total_time = 0.0
    for r in reports:
        if r.skipped_reason:
            print(f"{r.slug:<20}{'SKIPPED':>10}{r.skipped_reason}")
            continue
        print(
            f"{r.slug:<20}{r.messages:>10}{r.threads:>10}{r.batches:>10}"
            f"{r.cost_usd:>10.3f}{r.words:>10}{r.timing.total:>10.1f}"
        )
        total_cost += r.cost_usd
        total_time += r.timing.total
    print("-" * len(header))
    print(
        f"{'TOTAL':<20}{'':>10}{'':>10}{'':>10}"
        f"{total_cost:>10.3f}{'':>10}{total_time:>10.1f}"
    )
    print(f"\nWall-clock: {wall_seconds:.1f}s")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--topic", help="Run a single topic slug from topics.yaml")
    grp.add_argument("--all", action="store_true", help="Run all topics")
    parser.add_argument("--rebuild", action="store_true", help="Ignore cache, rerun from scratch")
    args = parser.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"DB not found: {DB_PATH}")
    if not TOPICS_YAML.exists():
        sys.exit(f"topics.yaml not found: {TOPICS_YAML}")

    CACHE_DIR.mkdir(exist_ok=True)
    ARTICLES_DIR.mkdir(exist_ok=True)

    topics = load_topics_yaml(TOPICS_YAML)
    if args.topic:
        if args.topic not in topics:
            sys.exit(f"Unknown topic: {args.topic}. Known: {list(topics)}")
        slugs = [args.topic]
    else:
        slugs = list(topics.keys())

    t0 = time.time()
    reports: list[TopicReport] = []
    for slug in slugs:
        try:
            reports.append(run_topic(slug, topics[slug], args.rebuild))
        except Exception as e:
            print(f"  [error] {slug}: {e}")
            reports.append(TopicReport(slug=slug, skipped_reason=f"error: {e}"))

    print_report(reports, time.time() - t0)


if __name__ == "__main__":
    main()
