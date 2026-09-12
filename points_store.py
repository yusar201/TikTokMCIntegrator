"""Long-term viewer points database (SQLite).

Tracks every viewer who sends coins, keyed by TikTok's PERMANENT numeric
user id (`event.user.id` / `id_str`), which never changes even when the
viewer renames their @username or display name. Username/nickname are
stored as cosmetic columns refreshed on every gift.

Design goals:
- Efficient for long-term growth: O(1) upsert per gift, indexed reads,
  WAL journal mode, no full-file rewrites (unlike the JSON logs).
- Thread-safe: all writes serialized through a module lock; connections
  are short-lived per operation.
- Append-only `gift_ledger` keeps per-gift history for future features
  (per-viewer detail, daily charts) without slowing the aggregate table.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Optional

_LOCK = threading.Lock()
_DB_PATH: Optional[str] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS viewers (
  user_id      TEXT PRIMARY KEY,
  username     TEXT NOT NULL DEFAULT '',
  nickname     TEXT NOT NULL DEFAULT '',
  avatar_url   TEXT NOT NULL DEFAULT '',
  total_coins  INTEGER NOT NULL DEFAULT 0,
  gift_count   INTEGER NOT NULL DEFAULT 0,
  first_seen   REAL NOT NULL,
  last_gift_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS gift_ledger (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id   TEXT NOT NULL,
  ts        REAL NOT NULL,
  coins     INTEGER NOT NULL,
  gift_id   TEXT NOT NULL DEFAULT '',
  gift_name TEXT NOT NULL DEFAULT '',
  kind      TEXT NOT NULL DEFAULT 'gift'
);
CREATE INDEX IF NOT EXISTS idx_viewers_coins ON viewers(total_coins DESC);
CREATE INDEX IF NOT EXISTS idx_viewers_last  ON viewers(last_gift_ts DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_user   ON gift_ledger(user_id, ts);
"""

# Ledger row kinds. 'gift' rows are real TikTok gifts and drive gift counts;
# 'manual' rows are operator corrections that move coins only.
KIND_GIFT = "gift"
KIND_MANUAL = "manual"
MANUAL_DEFAULT_NOTE = "Manual adjustment"
ADJUST_OPERATIONS = ("set", "add", "remove")

_SORTS = {
    "coins": "total_coins DESC, last_gift_ts DESC",
    "recent": "last_gift_ts DESC",
    "name": "nickname COLLATE NOCASE ASC, total_coins DESC",
}


def init(db_path: str) -> None:
    """Point the store at a specific database file (creates schema)."""
    global _DB_PATH
    db_path = os.path.abspath(db_path)
    with _LOCK:
        if _DB_PATH == db_path:
            return
        _DB_PATH = db_path
        _connect().close()


def _default_path() -> str:
    import paths
    return os.path.join(paths.DATA_DIR, "points.db")


def _connect() -> sqlite3.Connection:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = _default_path()
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass  # drvfs quirks: fall back to default rollback journal
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an older database up to the current schema.

    ``CREATE TABLE IF NOT EXISTS`` leaves pre-existing tables untouched, so
    databases created before manual adjustments lack ``gift_ledger.kind``.
    Existing rows are all real gifts, which is exactly the column default.
    """
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(gift_ledger)")}
    except sqlite3.Error:
        return
    if not columns or "kind" in columns:
        return
    try:
        with conn:
            conn.execute(
                f"ALTER TABLE gift_ledger ADD COLUMN kind TEXT NOT NULL "
                f"DEFAULT '{KIND_GIFT}'"
            )
    except sqlite3.Error as e:
        print(f"[POINTS] gift_ledger.kind migration failed: {e}")


def record_gift(
    user_id: str,
    username: str = "",
    nickname: str = "",
    avatar_url: str = "",
    coins: int = 0,
    gift_id: str = "",
    gift_name: str = "",
    ts: Optional[float] = None,
) -> None:
    """Record one completed gift: upsert viewer aggregate + append ledger row.

    Identity rule: `user_id` must be the permanent TikTok user id when known.
    Cosmetic fields (username/nickname/avatar) are refreshed whenever a
    non-empty value arrives, so renames self-heal on the next gift.
    """
    user_id = str(user_id or "").strip()
    if not user_id:
        return
    try:
        coins = max(0, int(coins or 0))
    except (TypeError, ValueError):
        coins = 0
    if coins <= 0:
        return
    now = float(ts if ts is not None else time.time())
    username = str(username or "").strip()
    nickname = str(nickname or "").strip()
    avatar_url = str(avatar_url or "").strip()

    with _LOCK:
        try:
            conn = _connect()
        except Exception as e:
            print(f"[POINTS] DB connect failed: {e}")
            return
        try:
            with conn:
                row = conn.execute(
                    "SELECT username, nickname, avatar_url FROM viewers WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if row is None:
                    conn.execute(
                        """INSERT INTO viewers
                           (user_id, username, nickname, avatar_url,
                            total_coins, gift_count, first_seen, last_gift_ts)
                           VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                        (user_id, username, nickname, avatar_url, coins, now, now),
                    )
                else:
                    conn.execute(
                        """UPDATE viewers SET
                             username = CASE WHEN ? <> '' THEN ? ELSE username END,
                             nickname = CASE WHEN ? <> '' THEN ? ELSE nickname END,
                             avatar_url = CASE WHEN ? <> '' THEN ? ELSE avatar_url END,
                             total_coins = total_coins + ?,
                             gift_count = gift_count + 1,
                             last_gift_ts = ?
                           WHERE user_id = ?""",
                        (
                            username, username,
                            nickname, nickname,
                            avatar_url, avatar_url,
                            coins, now, user_id,
                        ),
                    )
                conn.execute(
                    "INSERT INTO gift_ledger (user_id, ts, coins, gift_id, gift_name, kind) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, now, coins, str(gift_id or ""), str(gift_name or ""),
                     KIND_GIFT),
                )
        except Exception as e:
            print(f"[POINTS] record_gift failed for {user_id}: {e}")
        finally:
            conn.close()


def adjust_coins(
    user_id: str,
    operation: str,
    amount,
    note: str = "",
    ts: Optional[float] = None,
) -> dict:
    """Manually correct one viewer's coin total (operator recovery path).

    Exists because gifts can be missed entirely when the app crashes or the
    TikTok connection drops mid-stream. The correction is written as a signed
    ``manual`` ledger row plus the matching aggregate update, so period views
    stay consistent with the all-time total and gift counts stay truthful.

    ``operation`` is ``set`` (write this exact total), ``add``, or ``remove``.
    ``amount`` is always a non-negative magnitude. Totals floor at zero, and
    the clamped signed delta actually applied is returned.
    """
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("user_id is required")
    operation = str(operation or "").strip().lower()
    if operation not in ADJUST_OPERATIONS:
        raise ValueError("operation must be set, add, or remove")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ValueError("amount must be a non-negative number")
    if isinstance(amount, float) and not amount.is_integer():
        raise ValueError("amount must be a whole number of coins")
    amount = int(amount)
    if amount < 0:
        raise ValueError("amount must be a non-negative number")

    now = float(ts if ts is not None else time.time())
    note = str(note or "").strip() or MANUAL_DEFAULT_NOTE

    with _LOCK:
        conn = _connect()
        try:
            with conn:
                row = conn.execute(
                    "SELECT total_coins, gift_count, last_gift_ts FROM viewers "
                    "WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if row is None:
                    raise LookupError(f"viewer {user_id} not found")

                current = int(row["total_coins"] or 0)
                if operation == "set":
                    target = amount
                elif operation == "add":
                    target = current + amount
                else:
                    target = current - amount
                target = max(0, target)
                delta = target - current

                if delta:
                    conn.execute(
                        "UPDATE viewers SET total_coins = ?, last_gift_ts = ? "
                        "WHERE user_id = ?",
                        (target, max(float(row["last_gift_ts"] or 0.0), now), user_id),
                    )
                    conn.execute(
                        "INSERT INTO gift_ledger "
                        "(user_id, ts, coins, gift_id, gift_name, kind) "
                        "VALUES (?, ?, ?, '', ?, ?)",
                        (user_id, now, delta, note, KIND_MANUAL),
                    )
            return {
                "user_id": user_id,
                "operation": operation,
                "amount": amount,
                "applied_delta": delta,
                "previous_coins": current,
                "total_coins": target,
                "gift_count": int(row["gift_count"] or 0),
                "note": note,
                "ts": now,
            }
        finally:
            conn.close()


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_timestamp(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def list_viewers(
    limit: int = 50,
    offset: int = 0,
    sort: str = "coins",
    q: str = "",
    since: Optional[float] = None,
    until: Optional[float] = None,
) -> dict:
    """Page viewer totals, optionally aggregated from gifts in ``[since, until)``."""
    limit = max(1, min(_coerce_int(limit, 50), 500))
    offset = max(0, _coerce_int(offset, 0))
    order = _SORTS.get(str(sort or "coins").strip().lower(), _SORTS["coins"])
    q = str(q or "").strip()
    since = _coerce_timestamp(since)
    until = _coerce_timestamp(until)

    search_sql = ""
    search_args: list = []
    if q:
        like = f"%{q}%"
        search_sql = "WHERE nickname LIKE ? OR username LIKE ? OR user_id = ?"
        search_args = [like, like, q]

    period_active = since is not None or until is not None
    if period_active:
        ledger_terms = []
        period_args: list = []
        if since is not None:
            ledger_terms.append("ts >= ?")
            period_args.append(since)
        if until is not None:
            ledger_terms.append("ts < ?")
            period_args.append(until)
        ledger_where = "WHERE " + " AND ".join(ledger_terms)
        base_sql = f"""
            SELECT v.user_id, v.username, v.nickname, v.avatar_url,
                   SUM(g.coins) AS total_coins,
                   SUM(CASE WHEN g.kind = '{KIND_GIFT}' THEN 1 ELSE 0 END) AS gift_count,
                   MIN(g.ts) AS first_seen,
                   MAX(g.ts) AS last_gift_ts
              FROM gift_ledger g
              JOIN viewers v ON v.user_id = g.user_id
              {ledger_where}
             GROUP BY v.user_id, v.username, v.nickname, v.avatar_url
        """
        base_args = period_args
    else:
        base_sql = """
            SELECT user_id, username, nickname, avatar_url, total_coins,
                   gift_count, first_seen, last_gift_ts
              FROM viewers
        """
        base_args = []

    empty = {
        "viewers": [], "total": 0, "total_viewers": 0,
        "total_coins": 0, "total_gifts": 0,
        "since": since, "until": until,
    }
    with _LOCK:
        try:
            conn = _connect()
        except Exception as e:
            return {**empty, "error": str(e)}
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM ({base_sql}) period_viewers {search_sql}",
                base_args + search_args,
            ).fetchone()["c"]
            rows = conn.execute(
                f"""SELECT * FROM ({base_sql}) period_viewers {search_sql}
                    ORDER BY {order} LIMIT ? OFFSET ?""",
                base_args + search_args + [limit, offset],
            ).fetchall()
            summary = conn.execute(
                f"""SELECT COUNT(*) AS viewers,
                            COALESCE(SUM(total_coins), 0) AS coins,
                            COALESCE(SUM(gift_count), 0) AS gifts
                       FROM ({base_sql}) period_viewers""",
                base_args,
            ).fetchone()
            return {
                "viewers": [dict(r) for r in rows],
                "total": total,
                "total_viewers": summary["viewers"],
                "limit": limit,
                "offset": offset,
                "total_coins": summary["coins"],
                "total_gifts": summary["gifts"],
                "since": since,
                "until": until,
            }
        except Exception as e:
            return {**empty, "error": str(e)}
        finally:
            conn.close()


def viewer_detail(user_id: str, history_limit: int = 100) -> dict:
    """One viewer's aggregate + most recent gift history (for future drill-down)."""
    user_id = str(user_id or "").strip()
    history_limit = max(1, min(_coerce_int(history_limit, 100), 1000))
    with _LOCK:
        try:
            conn = _connect()
        except Exception as e:
            return {"viewer": None, "history": [], "error": str(e)}
        try:
            row = conn.execute(
                "SELECT * FROM viewers WHERE user_id = ?", (user_id,)
            ).fetchone()
            history = conn.execute(
                "SELECT ts, coins, gift_id, gift_name, kind FROM gift_ledger "
                "WHERE user_id = ? ORDER BY ts DESC LIMIT ?",
                (user_id, history_limit),
            ).fetchall()
            return {"viewer": dict(row) if row else None, "history": [dict(h) for h in history]}
        finally:
            conn.close()
