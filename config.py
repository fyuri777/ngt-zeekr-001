"""
Zeekr 001 project config.
Reads from the tg-collector messages.db and maintains a filtered zeekr.db.
"""
from pathlib import Path

# Paths — adjust if tg-collector lives elsewhere
TG_COLLECTOR_DIR = Path(__file__).parent.parent / "tg-collector"
SOURCE_DB = TG_COLLECTOR_DIR / "messages.db"
ZEEKR_DB  = Path(__file__).parent / "zeekr.db"

# 001-specific topic IDs in @zeekrclub
TOPICS_001 = {
    129577: "001 Дорест",
    489048: "001 Рест (+FR)",
    730610: "ПО/МА — 001 Рест",
    129581: "ПО/МА — 001 Дорест",
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
CHANNELS = ["zeekrclub", "zeekrclub_tech", "chat_zeekry"]
