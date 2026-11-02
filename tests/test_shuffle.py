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


def test_reconcile_shuffles_new_photos_among_themselves(conn):
    # A big batch of new photos into a tiny remainder must not come out in id order.
    _add_photo(conn, "/root/0.jpg")
    shuffle.initialize_shuffle(conn, seed=1)

    new_ids = [_add_photo(conn, f"/root/new{i}.jpg") for i in range(50)]
    shuffle.reconcile_after_scan(conn, rng=random.Random(5))

    order = [r["photo_id"] for r in conn.execute("SELECT photo_id FROM shuffle_order ORDER BY position")]
    assert [pid for pid in order if pid in set(new_ids)] != new_ids


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


def _order(conn):
    return [r["photo_id"] for r in conn.execute("SELECT photo_id FROM shuffle_order ORDER BY position")]


def test_skip_to_eligible_moves_forward_and_wraps(conn):
    for i in range(6):
        _add_photo(conn, f"/root/{i}.jpg")
    shuffle.initialize_shuffle(conn, seed=4)
    order = _order(conn)
    described = {order[1], order[4]}
    for pid in described:
        conn.execute("UPDATE photos SET description='hi' WHERE id=?", (pid,))
    conn.execute("UPDATE photos SET description='   ' WHERE id=?", (order[2],))

    assert shuffle.skip_to_eligible(conn, require_description=True)
    assert db.get_state(conn, "cursor") == "1"
    shuffle.advance_cursor(conn)
    assert shuffle.skip_to_eligible(conn, require_description=True)
    assert db.get_state(conn, "cursor") == "4"
    shuffle.advance_cursor(conn)
    assert shuffle.skip_to_eligible(conn, require_description=True)
    assert db.get_state(conn, "cursor") == "1"  # wrapped


def test_skip_to_eligible_false_when_none_described(conn):
    for i in range(3):
        _add_photo(conn, f"/root/{i}.jpg")
    shuffle.initialize_shuffle(conn, seed=4)
    shuffle.advance_cursor(conn)
    assert not shuffle.skip_to_eligible(conn, require_description=True)
    assert db.get_state(conn, "cursor") == "1"


def test_skip_to_eligible_always_skips_delete_notes(conn):
    for i in range(3):
        _add_photo(conn, f"/root/{i}.jpg")
    shuffle.initialize_shuffle(conn, seed=4)
    order = _order(conn)
    conn.execute("UPDATE photos SET description='Delete please' WHERE id=?", (order[0],))
    conn.execute("UPDATE photos SET description='Lake Tekapo' WHERE id=?", (order[2],))

    # Without requiring a description: skips only the delete-marked photo.
    assert shuffle.skip_to_eligible(conn, require_description=False)
    assert db.get_state(conn, "cursor") == "1"
    # Requiring one: also skips the undescribed photo.
    assert shuffle.skip_to_eligible(conn, require_description=True)
    assert db.get_state(conn, "cursor") == "2"


def test_skip_to_eligible_honors_date_range(conn):
    for i in range(3):
        _add_photo(conn, f"/root/{i}.jpg")
    shuffle.initialize_shuffle(conn, seed=4)
    order = _order(conn)
    for pid, epoch in zip(order, (100.0, 200.0, 300.0)):
        conn.execute("UPDATE photos SET date_epoch=? WHERE id=?", (epoch, pid))

    assert shuffle.skip_to_eligible(conn, False, date_range=(150.0, None))
    assert db.get_state(conn, "cursor") == "1"
    shuffle.advance_cursor(conn)
    assert shuffle.skip_to_eligible(conn, False, date_range=(150.0, 250.0))
    assert db.get_state(conn, "cursor") == "1"  # 300 is out of range: wrapped back
    assert not shuffle.skip_to_eligible(conn, False, date_range=(400.0, None))
