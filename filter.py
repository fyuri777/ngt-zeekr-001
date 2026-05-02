"""
Extract 001-relevant messages from messages.db → zeekr.db.

Inclusion criteria:
  1. All messages in the 4 dedicated 001 topics (TOPICS_001)
  2. Any message in ANY other topic that mentions "001" in text
     + the full reply thread containing that message (replies don't repeat "001"
       but are contextually relevant — e.g. "попробуй ребут" answering "001 не работает")

Run: python filter.py [--rebuild]
"""
import sqlite3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tg-collector"))

from config import SOURCE_DB, ZEEKR_DB, TOPIC_IDS_001


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

MSG_COLS = "m.id, m.channel_id, m.channel_name, m.date, m.text, m.views, m.forwards, m.reply_to_msg_id, m.from_id, m.from_name, m.raw_json, m.topic_id"
MSG_COLS_BARE = "id, channel_id, channel_name, date, text, views, forwards, reply_to_msg_id, from_id, from_name, raw_json, topic_id"


def find_thread_root(src, msg_id, channel_name, topic_id):
    """Walk UP reply chain, stop before topic root (same logic as search_core)."""
    current = msg_id
    seen = set()
    while current and current not in seen:
        seen.add(current)
        row = src.execute(
            "SELECT reply_to_msg_id FROM messages WHERE id=? AND channel_name=?",
            (current, channel_name)
        ).fetchone()
        if not row or not row[0]:
            break
        parent_id = row[0]
        if parent_id == topic_id:
            break
        if not src.execute(
            "SELECT 1 FROM messages WHERE id=? AND channel_name=?",
            (parent_id, channel_name)
        ).fetchone():
            break
        current = parent_id
    return current


def fetch_thread(src, root_id, channel_name):
    """Return all messages in the reply chain rooted at root_id (max 100)."""
    rows = src.execute(f"""
        WITH RECURSIVE descendants(id) AS (
            SELECT ?
            UNION ALL
            SELECT m.id FROM messages m
            JOIN descendants d ON m.reply_to_msg_id = d.id
            WHERE m.channel_name = ?
        )
        SELECT DISTINCT {MSG_COLS}
        FROM messages m JOIN descendants d ON m.id = d.id
        ORDER BY m.date ASC
        LIMIT 100
    """, (root_id, channel_name)).fetchall()
    return rows


def rebuild(src: sqlite3.Connection, dst: sqlite3.Connection):
    dst.executescript(ZEEKR_SCHEMA)

    # Copy channels and topics metadata
    dst.executemany("INSERT OR REPLACE INTO channels VALUES (?,?,?,?,?,?)",
                    src.execute("SELECT * FROM channels").fetchall())
    dst.executemany("INSERT OR REPLACE INTO topics VALUES (?,?,?)",
                    src.execute("SELECT * FROM topics").fetchall())

    all_rows = {}

    # Pass 1: all messages from dedicated 001 topics
    topic_ids_sql = ",".join(str(i) for i in TOPIC_IDS_001)
    rows = src.execute(f"""
        SELECT {MSG_COLS_BARE} FROM messages WHERE topic_id IN ({topic_ids_sql})
    """).fetchall()
    for r in rows:
        all_rows[r[0]] = r
    count_dedicated = len(rows)
    print(f"  Pass 1: {count_dedicated} messages from dedicated 001 topics")

    # Pass 2: seed messages — any message outside 001 topics mentioning "001"
    seed_rows = src.execute(f"""
        SELECT {MSG_COLS_BARE} FROM messages
        WHERE topic_id NOT IN ({topic_ids_sql})
          AND (text LIKE '%001%')
    """).fetchall()
    print(f"  Pass 2: {len(seed_rows)} seed messages mentioning '001' in other topics")

    # Pass 3: expand each seed to its full reply thread
    threads_added = 0
    seen_roots = set()
    for seed in seed_rows:
        msg_id      = seed[0]
        channel     = seed[2]
        topic_id    = seed[11]

        root_id = find_thread_root(src, msg_id, channel, topic_id)
        if root_id in seen_roots:
            continue
        seen_roots.add(root_id)

        thread = fetch_thread(src, root_id, channel)
        before = len(all_rows)
        for r in thread:
            all_rows[r[0]] = r
        threads_added += len(all_rows) - before

    print(f"  Pass 3: +{threads_added} messages from reply threads around seeds")

    dst.executemany(
        f"INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        all_rows.values()
    )
    dst.commit()
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
