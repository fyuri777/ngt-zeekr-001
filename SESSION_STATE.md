# Zeekr 001 Knowledge Portal — Session State
# Updated: 2026-05-03

## What this project is
Telegram chat → structured owner's handbook (yu7.site-style) for Zeekr 001 EV.
Synthesis pipeline: SQL gather → LLM batch-extract → merge → compose → static HTML.

## Current status
**Phase A (synthesis pipeline) — VALIDATED.**
Pipeline produces yu7.site-quality articles. 3 test articles built on 131k filtered messages. All synthesis runs FREE via `claude-batch` (Sonnet 4.6 from Claude Code subscription).

**Phase B (portal HTML) — MVP DONE.**
3-article static portal renders locally at http://localhost:8000. yu7-inspired typography, evidence-badge pills, mobile-responsive.

**Next planned: speed up synthesis (parallel batches + Haiku for extract + bigger chunks).**

## Files

| File | Role |
|---|---|
| `config.py` | DB paths, channel IDs, TOPIC_IDS_001 |
| `filter.py` | messages.db → zeekr.db (3-pass filter, +indexes added) |
| `search.py` | FTS5 search wrapper |
| `synthesize.py` | Main pipeline: gather → extract → merge → compose |
| `prompts.py` | EXTRACT_PROMPT, MERGE_PROMPT, COMPOSE_PROMPT |
| `topics.yaml` | 3 topic specs (antifreeze, doors, tire-pressure) |
| `build_portal.py` | Articles MD → static HTML portal |

## Pipeline architecture

```
messages.db (442k msgs from 3 channels)
        ↓ filter.py --rebuild (60s with indexes)
zeekr.db (131,644 messages, 329 MB)
        ↓ synthesize.py --topic <slug> --rebuild
        │   Stage 1 GATHER (SQL, instant)
        │   Stage 2 EXTRACT (LLM batches × N, sequential — TODO: parallel)
        │   Stage 3 MERGE (LLM single call)
        │   Stage 4 COMPOSE (LLM single call)
articles/<slug>.md
        ↓ build_portal.py
portal/<slug>.html + portal/index.html
```

## Performance baseline (Sonnet 4.6 via claude-batch, sequential)

| Topic | Messages | Threads | Batches | Words | Wall-clock |
|---|---|---|---|---|---|
| antifreeze | 1 427 | 918 | 14 | 2 176 | 23.7 min |
| doors | 2 457 | 1 650 | 24 | 1 911 | 30.0 min |
| tire-pressure | 938 | 600 | 9 | 1 799 | 13.3 min |

Cost: $0.00 (claude-batch uses Claude Code subscription).

## Performance — after speedup v2 (2026-05-03)

Implemented:
- `claude_call()` now takes a `model=` keyword (default `sonnet`). The
  internal extract loop reads `EXTRACT_MODEL` so we can swap Haiku/Sonnet
  without further surgery.
- `stage_merge` is bypassed for topics with `n_batches <= 3` and replaced
  by `_python_merge()` (concat + first-100-char dedup, anchor heuristic).
  Saves an LLM merge call (≈80–150s) on small topics. None of the
  currently published 9 articles hit this path; expect savings on future
  thin topics.
- `claude-batch -p ... --output-format json` verified to return
  `usage.cache_read_input_tokens` and `cache_creation_input_tokens` —
  caching observability is achievable. Not wired into the pipeline yet
  (see "future").

A/B test verdict — Haiku for extract: **REVERTED**.

| Topic | Sonnet facts | Haiku facts | Ratio | Parse errors | Parts lost |
|---|---|---|---|---|---|
| antifreeze | 222 | 94 | 0.42 | 3/7 batches | 3 (8891307621, 8896691417, 6608340523) |
| doors | 447 | 164 | 0.37 | 6/12 batches | 0 |
| tire-pressure | 86 | 131 | 1.52 | 0/5 batches | 0 |

Failure mode: Haiku 4.5 frequently emits structurally invalid JSON on the
RU extract prompt (closes objects with `]`, unescaped quotes inside
strings). 3/7 → 6/12 parse errors discard whole batches of findings.
Critical part numbers explicitly listed in the speedup brief
(`8891307621`, `8896691417`) were lost on antifreeze. `EXTRACT_MODEL`
left at `sonnet`.

Validation rebuild on tire-pressure (Sonnet, with skip-merge code in
place but n_batches=5 so still LLM merge):
`297.4s wall-clock` (gather 49s, extract 52s, merge 100s, compose 96s).
Article preserves both critical TPMS part numbers and the H2 sections
"Спорные моменты" / "Предупреждения".

### Future (not implemented)

- **Anthropic API for explicit caching** (Step 5 in the brief). Would need
  ~$5–10 for the remaining 40 articles via Batch API + cache_control on
  the EXTRACT_PROMPT_PREFIX. User previously declined paid API; revisit if
  Sonnet subscription throughput becomes a blocker.
- **Cache hit rate logging.** `--output-format json` works through
  claude-batch (verified — returns `cache_read_input_tokens`). Plumbing
  it into `claude_call()` requires changing the response parser to read
  `.result` from the JSON envelope; deferred since it's pure observability
  with no current decision riding on it.
- **Better extract model.** Sonnet 4.7 (not yet on subscription path) may
  match Sonnet 4.6 quality at lower latency; rerun the A/B when available.

## Known limitations

1. **Extract stage sequential** — biggest speedup target.
2. **No incremental updates** — rerunning re-processes all messages.
3. **Article length 2k words** — user feedback: a bit long. Adjust COMPOSE_PROMPT to 1200-2200.
4. **Only 3/48 articles built** — full taxonomy in `../orchestrator/.runs/tg-knowledge-portal-2026-05/taxonomy.md`.
5. **No external sources** — only Telegram. Adding YouTube/Exa enrichment is a future "Phase C".
6. **Telegram parser stops at Aug 2024** — collect.py needs another pass for older history (low priority).

## Run commands

```bash
# Refresh data
cd ../tg-collector && .venv/bin/python collect.py --no-join              # daily delta
cd ../zeekr-001    && ../tg-collector/.venv/bin/python filter.py --rebuild  # rebuild filtered DB

# Synthesize articles
../tg-collector/.venv/bin/python synthesize.py --topic <slug> --rebuild
../tg-collector/.venv/bin/python synthesize.py --all

# Build portal
../tg-collector/.venv/bin/python build_portal.py
cd portal && python3 -m http.server 8000
```

## Repo
- Local: `/Users/alexey/Downloads/ngt/zeekr-001/`
- GitHub: `github.com/fyuri777/ngt-zeekr-001` (private)
- Latest commit: 13664c1 (filter.py 3-pass logic)
- Uncommitted: synthesize.py, prompts.py, topics.yaml, build_portal.py, SESSION_STATE.md, .gitignore updates

## Meta-task docs
Methodology + taxonomy + research lives in run folder:
`/Users/alexey/Downloads/ngt/orchestrator/.runs/tg-knowledge-portal-2026-05/`
- `pre-brief.md` — initial scope
- `taxonomy.md` — 48 articles in 10 sections
- `methodology-synthesis.md` — research synthesis (yu7 + larikoz + orchestrator)
- `gemini-topic-discovery.md` — raw topic discovery output
