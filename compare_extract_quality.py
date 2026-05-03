"""A/B compare extract quality: Sonnet baseline vs Haiku run.

Counts JSON parse success rate, total facts per category, and
distinct part numbers / price mentions per topic. Used once after
the speedup-v2 Haiku-for-extract switch to decide commit vs revert.

Run:
    python compare_extract_quality.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
ARTICLES = ROOT / "articles"

TOPICS = ["antifreeze", "doors", "tire-pressure"]
CATEGORIES = ("key_questions", "key_answers", "controversies", "warnings", "specific_data")

PART_RE = re.compile(r"\b\d{8,12}\b")
PRICE_RE = re.compile(r"\d+\s*(?:₽|тыс|млн|рубл|руб|USD|\$)")


def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def _topic_stats(cache_dir: Path, article_path: Path) -> dict:
    batches_dir = cache_dir / "02_batches"
    n_batches = 0
    n_parse_errors = 0
    counts = {k: 0 for k in CATEGORIES}

    if batches_dir.exists():
        for f in sorted(batches_dir.glob("*.json")):
            n_batches += 1
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("_parse_error"):
                n_parse_errors += 1
            for k in CATEGORIES:
                counts[k] += len(data.get(k) or [])

    article_text = article_path.read_text(encoding="utf-8") if article_path.exists() else ""
    parts = set(PART_RE.findall(article_text))
    prices = set(PRICE_RE.findall(article_text))

    return {
        "n_batches": n_batches,
        "n_parse_errors": n_parse_errors,
        "counts": counts,
        "total_facts": sum(counts.values()),
        "distinct_parts": parts,
        "distinct_prices": prices,
        "article_words": len(article_text.split()),
    }


def main() -> None:
    print(f"{'Topic':<16}{'Side':<10}{'Btchs':>6}{'Errs':>5}{'Facts':>7}{'Parts':>7}{'Prices':>8}{'Words':>8}")
    print("-" * 67)

    summary = []
    for topic in TOPICS:
        sonnet = _topic_stats(
            CACHE / f"{topic}.sonnet-baseline",
            ARTICLES / f"{topic}.sonnet-baseline.md",
        )
        haiku = _topic_stats(
            CACHE / topic,
            ARTICLES / f"{topic}.md",
        )

        for side, s in (("sonnet", sonnet), ("haiku", haiku)):
            print(
                f"{topic:<16}{side:<10}{s['n_batches']:>6}{s['n_parse_errors']:>5}"
                f"{s['total_facts']:>7}{len(s['distinct_parts']):>7}"
                f"{len(s['distinct_prices']):>8}{s['article_words']:>8}"
            )

        # Per-topic delta
        if sonnet["total_facts"]:
            ratio = haiku["total_facts"] / sonnet["total_facts"]
        else:
            ratio = 0.0
        parts_lost = sonnet["distinct_parts"] - haiku["distinct_parts"]
        parts_gained = haiku["distinct_parts"] - sonnet["distinct_parts"]
        print(
            f"  -> facts ratio={ratio:.2f}, parts_lost={len(parts_lost)} "
            f"({sorted(parts_lost)[:5]}), parts_gained={len(parts_gained)}"
        )
        summary.append({
            "topic": topic,
            "facts_ratio": ratio,
            "parts_lost": sorted(parts_lost),
            "parts_gained": sorted(parts_gained),
            "sonnet_parse_errors": sonnet["n_parse_errors"],
            "haiku_parse_errors": haiku["n_parse_errors"],
        })

    print("\nVerdict (rule: facts ≥80% AND ≤2 parts lost per topic):")
    overall_pass = True
    for s in summary:
        ok = s["facts_ratio"] >= 0.80 and len(s["parts_lost"]) <= 2
        overall_pass &= ok
        print(f"  {s['topic']}: facts={s['facts_ratio']:.2f}, "
              f"parts_lost={len(s['parts_lost'])} -> {'PASS' if ok else 'FAIL'}")
    print(f"\nOverall: {'COMMIT' if overall_pass else 'REVERT'}")


if __name__ == "__main__":
    main()
