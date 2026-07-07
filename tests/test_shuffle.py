import random
import sqlite3
import time

import pytest

from riffle import db, shuffle


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)
    return conn


def _add_photo(conn: sqlite3.Connection, path: str, missing: bool = False) -> int:
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO photos (
            path, root_folder, size, mtime, content_hash, date_display,
            date_epoch, date_source, title, description, missing_at,
            first_seen_at, last_scanned_at
        ) VALUES (?, '/root', 100, ?, 'hash', 'Jan 1, 2020', ?, 'mtime', NULL, NULL, ?, ?, ?)
        """,
        (path, now, now, now if missing else None, now, now),
    )
    return cur.lastrowid


@pytest.fixture
def conn():
    c = _make_conn()
    yield c
    c.close()


def test_initialize_shuffle_covers_all_photos_once(conn):
    ids = [_add_photo(conn, f"/root/{i}.jpg") for i in range(20)]
    shuffle.initialize_shuffle(conn, seed=42)

    rows = conn.execute("SELECT photo_id, position FROM shuffle_order ORDER BY position").fetchall()
    assert [r["position"] for r in rows] == list(range(20))
    assert {r["photo_id"] for r in rows} == set(ids)
    assert db.get_state(conn, "cursor") == "0"


def test_reconcile_adds_new_photos_only_into_unseen_remainder(conn):
    ids = [_add_photo(conn, f"/root/{i}.jpg") for i in range(10)]
    shuffle.initialize_shuffle(conn, seed=1)

    # Advance the cursor to simulate having shown the first 4 photos.
    for _ in range(4):
        shuffle.advance_cursor(conn)
    assert int(db.get_state(conn, "cursor")) == 4

    seen_photo_ids_before = {
        r["photo_id"]
        for r in conn.execute("SELECT photo_id FROM shuffle_order WHERE position < 4").fetchall()
    }

    new_ids = [_add_photo(conn, f"/root/new{i}.jpg") for i in range(5)]
    shuffle.reconcile_after_scan(conn, rng=random.Random(7))

    # Cursor and the already-seen prefix are untouched.
    assert int(db.get_state(conn, "cursor")) == 4
    seen_photo_ids_after = {
        r["photo_id"]
        for r in conn.execute("SELECT photo_id FROM shuffle_order WHERE position < 4").fetchall()
    }
    assert seen_photo_ids_before == seen_photo_ids_after

    # New photos only appear at position >= cursor.
    all_rows = conn.execute("SELECT photo_id, position FROM shuffle_order ORDER BY position").fetchall()
    positions_by_id = {r["photo_id"]: r["position"] for r in all_rows}
    for new_id in new_ids:
        assert positions_by_id[new_id] >= 4

    # Total count grew by exactly the number of new photos, densely numbered.
    assert len(all_rows) == 15
    assert [r["position"] for r in all_rows] == list(range(15))


def test_reconcile_removes_missing_photos_and_adjusts_cursor(conn):
    ids = [_add_photo(conn, f"/root/{i}.jpg") for i in range(10)]
    shuffle.initialize_shuffle(conn, seed=2)
    for _ in range(5):
        shuffle.advance_cursor(conn)
    assert int(db.get_state(conn, "cursor")) == 5

    # Mark two already-seen photos (position < cursor) as missing.
    seen_ids = [
        r["photo_id"]
        for r in conn.execute("SELECT photo_id FROM shuffle_order WHERE position < 5").fetchall()
    ]
    for pid in seen_ids[:2]:
        conn.execute("UPDATE photos SET missing_at=? WHERE id=?", (time.time(), pid))

    shuffle.reconcile_after_scan(conn, rng=random.Random(3))

    # Two seen items vanished -> cursor decremented by 2.
    assert int(db.get_state(conn, "cursor")) == 3

    remaining_rows = conn.execute("SELECT photo_id, position FROM shuffle_order ORDER BY position").fetchall()
    assert len(remaining_rows) == 8
    assert [r["position"] for r in remaining_rows] == list(range(8))
    remaining_ids = {r["photo_id"] for r in remaining_rows}
    assert not (remaining_ids & set(seen_ids[:2]))


def test_advance_cursor_wraps_without_reshuffle_by_default(conn):
    for i in range(3):
        _add_photo(conn, f"/root/{i}.jpg")
    shuffle.initialize_shuffle(conn, seed=5)
    order_before = [
        r["photo_id"] for r in conn.execute("SELECT photo_id FROM shuffle_order ORDER BY position").fetchall()
    ]

    for _ in range(3):
        shuffle.advance_cursor(conn, reshuffle_on_wrap=False)

    assert int(db.get_state(conn, "cursor")) == 0
    order_after = [
        r["photo_id"] for r in conn.execute("SELECT photo_id FROM shuffle_order ORDER BY position").fetchall()
    ]
    assert order_before == order_after


def test_get_photo_at_cursor_and_status_summary(conn):
    _add_photo(conn, "/root/a.jpg")
    _add_photo(conn, "/root/b.jpg")
    shuffle.initialize_shuffle(conn, seed=9)

    status = shuffle.status_summary(conn)
    assert status.total == 2
    assert status.cursor == 0
    assert status.remaining_in_cycle == 2
    assert status.current_photo is not None

    shuffle.advance_cursor(conn)
    status = shuffle.status_summary(conn)
    assert status.cursor == 1
    assert status.remaining_in_cycle == 1
