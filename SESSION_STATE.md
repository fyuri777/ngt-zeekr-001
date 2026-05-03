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
