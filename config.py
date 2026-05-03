"""
Zeekr 001 project config.
Reads from the tg-collector messages.db and maintains a filtered zeekr.db.
"""
from pathlib import Path

# Paths — adjust if tg-collector lives elsewhere
TG_COLLECTOR_DIR = Path(__file__).parent.parent / "tg-collector"
SOURCE_DB = TG_COLLECTOR_DIR / "messages.db"
ZEEKR_DB  = Path(__file__).parent / "zeekr.db"

# 001-specific topic IDs across all collected channels.
# Topic IDs are per-supergroup — same number can mean different things in different
# channels, so we ALSO check that messages with these IDs actually came from a known
# 001-discussing channel (handled implicitly: only @zeekrclub and @zeekrclubrus have
# these IDs).
TOPICS_001 = {
    # @zeekrclub
    129577: "001 Дорест",
    489048: "001 Рест (+FR)",
    730610: "ПО/МА — 001 Рест",
    129581: "ПО/МА — 001 Дорест",
    # @zeekrclubrus — only the ПО/МА topic explicitly mentions 001 in its title;
    # other zeekrclubrus topics are model-mixed and rely on Pass 2 (text LIKE '%001%').
    180635: "Техничка / ПО и МА (X, 001, 007, 009, 7x)",
}

# General topics in @zeekrclub that often contain 001-relevant discussion
TOPICS_GENERAL_RELEVANT = {
    3003:  "Зарядка и Батарея",
    2049:  "Обслуживание и ремонт",
    1520:  "Масло",
}

TOPIC_IDS_001 = set(TOPICS_001.keys())
TOPIC_IDS_GENERAL = set(TOPICS_GENERAL_RELEVANT.keys())

# All Zeekr channels collected
CHANNELS = ["zeekrclub", "zeekrclub_tech", "chat_zeekry", "zeekrclubrus"]
