from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

from riffle.db import get_state, set_state


@dataclass
class PhotoRow:
    id: int
    path: str
    date_display: str
    title: str | None
    description: str | None


@dataclass
class ShuffleStatus:
    cursor: int
    total: int
    remaining_in_cycle: int
    current_photo: PhotoRow | None


def has_shuffle_order(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM shuffle_order LIMIT 1").fetchone() is not None


def initialize_shuffle(conn: sqlite3.Connection, seed: int | None = None) -> None:
    """Shuffle the full manifest and reset the cursor. Used on the very first scan."""
    rng = random.Random(seed)
    ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM photos WHERE missing_at IS NULL").fetchall()
    ]
    rng.shuffle(ids)

    conn.execute("DELETE FROM shuffle_order")
    conn.executemany(
        "INSERT INTO shuffle_order(position, photo_id) VALUES (?, ?)",
        list(enumerate(ids)),
    )
    set_state(conn, "cursor", "0")
    conn.commit()


def reconcile_after_scan(conn: sqlite3.Connection, rng: random.Random | None = None) -> None:
    """After a rescan: drop removed photos, insert new ones into the unseen
    remainder at random positions, leaving the already-seen prefix and the
    cursor otherwise untouched.
    """
    rng = rng or random.Random()

    try:
        cursor = int(get_state(conn, "cursor", "0"))

        missing_rows = conn.execute(
            """
            SELECT so.position AS position, so.photo_id AS photo_id
            FROM shuffle_order so
            JOIN photos p ON p.id = so.photo_id
            WHERE p.missing_at IS NOT NULL
            """
        ).fetchall()

        if missing_rows:
            removed_ids = {row["photo_id"] for row in missing_rows}
            num_removed_before_cursor = sum(1 for row in missing_rows if row["position"] < cursor)
            cursor = max(cursor - num_removed_before_cursor, 0)

            remaining_rows = conn.execute(
                "SELECT photo_id FROM shuffle_order ORDER BY position"
            ).fetchall()
            remaining_ids = [r["photo_id"] for r in remaining_rows if r["photo_id"] not in removed_ids]

            conn.execute("DELETE FROM shuffle_order")
            conn.executemany(
                "INSERT INTO shuffle_order(position, photo_id) VALUES (?, ?)",
                list(enumerate(remaining_ids)),
            )

        new_ids = [
            row["id"]
            for row in conn.execute(
                """
                SELECT p.id AS id FROM photos p
                LEFT JOIN shuffle_order so ON so.photo_id = p.id
                WHERE so.photo_id IS NULL AND p.missing_at IS NULL
                """
            ).fetchall()
        ]

        if new_ids:
            # Shuffle the new photos themselves too -- random slots alone keep
            # them in id (i.e. folder/filename) order relative to each other.
            rng.shuffle(new_ids)
            remainder = [
                row["photo_id"]
                for row in conn.execute(
                    "SELECT photo_id FROM shuffle_order WHERE position >= ? ORDER BY position",
                    (cursor,),
                ).fetchall()
            ]
            m, k = len(remainder), len(new_ids)
            slots = set(rng.sample(range(m + k), k))

            merged: list[int] = []
            remainder_iter = iter(remainder)
            new_iter = iter(new_ids)
            for i in range(m + k):
                merged.append(next(new_iter) if i in slots else next(remainder_iter))

            conn.execute("DELETE FROM shuffle_order WHERE position >= ?", (cursor,))
            conn.executemany(
                "INSERT INTO shuffle_order(position, photo_id) VALUES (?, ?)",
                [(cursor + i, photo_id) for i, photo_id in enumerate(merged)],
            )

        set_state(conn, "cursor", str(cursor))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _reshuffle_all(conn: sqlite3.Connection, rng: random.Random) -> None:
    ids = [row["photo_id"] for row in conn.execute("SELECT photo_id FROM shuffle_order").fetchall()]
    rng.shuffle(ids)
    conn.execute("DELETE FROM shuffle_order")
    conn.executemany(
        "INSERT INTO shuffle_order(position, photo_id) VALUES (?, ?)",
        list(enumerate(ids)),
    )


def skip_to_eligible(
    conn: sqlite3.Connection, require_description: bool, reshuffle_on_wrap: bool = False
) -> bool:
    """Move the cursor forward to the next photo worth showing, wrapping to
    the start of the order (and reshuffling, if configured) like
    advance_cursor does. Photos whose description mentions "delete" (notes
    like "delete please") are always skipped; with require_description, so
    are photos with no description. Photos skipped over count as seen for
    this cycle. Returns False, leaving the cursor alone, if none qualify.
    """
    has_description = "TRIM(COALESCE(p.description, '')) != ''" if require_description else "1"
    # LIKE is case-insensitive for ASCII in SQLite, so this catches "Delete" too.
    query = f"""
        SELECT MIN(so.position) AS position
        FROM shuffle_order so
        JOIN photos p ON p.id = so.photo_id
        WHERE so.position >= ?
          AND {has_description}
          AND COALESCE(p.description, '') NOT LIKE '%delete%'
    """
    cursor = int(get_state(conn, "cursor", "0"))
    position = conn.execute(query, (cursor,)).fetchone()["position"]
    if position is None:
        if conn.execute(query, (0,)).fetchone()["position"] is None:
            return False
        if reshuffle_on_wrap:
            _reshuffle_all(conn, random.Random())
        position = conn.execute(query, (0,)).fetchone()["position"]
    if position != cursor:
        set_state(conn, "cursor", str(position))
    conn.commit()
    return True


def get_photo_at_cursor(conn: sqlite3.Connection) -> PhotoRow | None:
    cursor = int(get_state(conn, "cursor", "0"))
    row = conn.execute(
        """
        SELECT p.id AS id, p.path AS path, p.date_display AS date_display,
               p.title AS title, p.description AS description
        FROM shuffle_order so
        JOIN photos p ON p.id = so.photo_id
        WHERE so.position = ?
        """,
        (cursor,),
    ).fetchone()
    if row is None:
        return None
    return PhotoRow(
        id=row["id"],
        path=row["path"],
        date_display=row["date_display"],
        title=row["title"],
        description=row["description"],
    )


def advance_cursor(conn: sqlite3.Connection, reshuffle_on_wrap: bool = False) -> int:
    total = conn.execute("SELECT COUNT(*) AS c FROM shuffle_order").fetchone()["c"]
    cursor = int(get_state(conn, "cursor", "0")) + 1
    if total == 0:
        cursor = 0
    elif cursor >= total:
        cursor = 0
        if reshuffle_on_wrap:
            _reshuffle_all(conn, random.Random())
    set_state(conn, "cursor", str(cursor))
    conn.commit()
    return cursor


def status_summary(conn: sqlite3.Connection) -> ShuffleStatus:
    total = conn.execute("SELECT COUNT(*) AS c FROM shuffle_order").fetchone()["c"]
    cursor = int(get_state(conn, "cursor", "0"))
    current = get_photo_at_cursor(conn)
    return ShuffleStatus(
        cursor=cursor,
        total=total,
        remaining_in_cycle=max(total - cursor, 0),
        current_photo=current,
    )
