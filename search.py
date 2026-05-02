"""
Search Zeekr 001 messages. Wraps tg_collector.search_core with zeekr.db defaults.

Usage:
  python search.py "зарядка проблема"
  python search.py "батарея зима" --with-threads --limit 10
  python search.py --stats
"""
import sys
from pathlib import Path

# Allow running without installing tg_collector as a package
sys.path.insert(0, str(Path(__file__).parent.parent / "tg-collector"))

from tg_collector.search_core import main as _main
from tg_collector.db import connect, init_db
from config import ZEEKR_DB


def main():
    # Inject zeekr.db as default by patching DEFAULT_DB before argparse runs
    import tg_collector.config as cfg
    cfg.DEFAULT_DB = ZEEKR_DB
    _main()


if __name__ == "__main__":
    main()
