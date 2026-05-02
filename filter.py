"""
Extract 001-relevant messages from messages.db → zeekr.db.

Inclusion criteria:
  1. Messages in any of the 4 dedicated 001 topics (TOPICS_001)
  2. Messages in general topics that mention "001" in text
  3. Reply chains anchored in 001 topics (via topic_id)

Run: python filter.py [--rebuild]
"""
import sqlite3
import argparse
from pathlib import Path
from config import SOURCE_DB, ZEEKR_DB, TOPIC_IDS_001, TOPIC_IDS_GENERAL


ZEEKR_SCHEMA = """
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY, username TEXT, title TEXT,
        type TEXT, members INTEGER, fetched_at TEXT
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER, channel_id INTEGER, channel_name TEXT,
        date TEXT, text TEXT, views INTEGER, forwards INTEGER,
        reply_to_msg_id INTEGER, from_id INTEGER, from_name TEXT,
        raw_json TEXT, topic_id INTEGER,
        PRIMARY KEY (id, channel_id)
    );
    CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY, channel_name TEXT, title TEXT
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
        USING fts5(text, channel_name, date, content=messages, content_rowid=rowid);
    CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, text, channel_name, date)
        VALUES (new.rowid, new.text, new.channel_name, new.date);
    END;
"""


def rebuild(src: sqlite3.Connection, dst: sqlite3.Connection):
    dst.executescript(ZEEKR_SCHEMA)

    # Copy channels
    rows = src.execute("SELECT * FROM channels").fetchall()
    dst.executemany("INSERT OR REPLACE INTO channels VALUES (?,?,?,?,?,?)", rows)

    # Copy topics
    rows = src.execute("SELECT * FROM topics").fetchall()
    dst.executemany("INSERT OR REPLACE INTO topics VALUES (?,?,?)", rows)

    topic_ids_sql = ",".join(str(i) for i in TOPIC_IDS_001)
    general_ids_sql = ",".join(str(i) for i in TOPIC_IDS_GENERAL)

    # Dedicated 001 topics — include all messages
    rows = src.execute(f"""
        SELECT id, channel_id, channel_name, date, text, views, forwards,
               reply_to_msg_id, from_id, from_name, raw_json, topic_id
        FROM messages
        WHERE topic_id IN ({topic_ids_sql})
    """).fetchall()
    count_001 = len(rows)

    # General topics — include only messages mentioning "001"
    general_rows = src.execute(f"""
        SELECT id, channel_id, channel_name, date, text, views, forwards,
               reply_to_msg_id, from_id, from_name, raw_json, topic_id
        FROM messages
        WHERE topic_id IN ({general_ids_sql})
          AND text LIKE '%001%'
    """).fetchall()
    count_general = len(general_rows)

    all_rows = {r[0]: r for r in rows}
    all_rows.update({r[0]: r for r in general_rows})

    dst.executemany(
        "INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        all_rows.values()
    )
    dst.commit()

    print(f"✓ Copied {count_001} messages from dedicated 001 topics")
    print(f"✓ Copied {count_general} messages from general topics mentioning '001'")
    print(f"✓ Total unique: {len(all_rows)} messages → {ZEEKR_DB}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop and recreate zeekr.db from scratch")
    args = parser.parse_args()

    if not SOURCE_DB.exists():
        print(f"✗ {SOURCE_DB} not found. Run tg-collector/collect.py first.")
        return

    if args.rebuild and ZEEKR_DB.exists():
        ZEEKR_DB.unlink()
        print(f"Dropped {ZEEKR_DB}")

    src = sqlite3.connect(SOURCE_DB)
    dst = sqlite3.connect(ZEEKR_DB)

    rebuild(src, dst)

    src.close()
    dst.close()


if __name__ == "__main__":
    main()
