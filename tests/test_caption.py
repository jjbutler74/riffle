import sqlite3
from datetime import date, datetime
from pathlib import Path

from riffle import db
from riffle.imaging.caption import date_line, details_line, source_name, years_ago
from riffle.scan.exif import tags_to_result
from riffle.scan.geocode import format_place

ROOT = Path("D:/Pictures/2023")


def test_source_name_strips_phone_and_year():
    assert source_name(ROOT / "JenniferPhone2023" / "a.jpg", ROOT) == "Jennifer"
    assert source_name(ROOT / "Sabrina2024" / "a.jpg", ROOT) == "Sabrina"


def test_source_name_walks_up_past_dated_subfolders():
    assert source_name(ROOT / "JasonPhone2023" / "2023-01-12" / "a.jpg", ROOT) == "Jason"


def test_source_name_skips_single_letters_and_hidden_names():
    assert source_name(ROOT / "IPhone2023" / "a.jpg", ROOT) is None
    assert source_name(ROOT / "Screenshot2023" / "a.jpg", ROOT, ["screenshot"]) is None


def test_source_name_ignores_folders_without_a_year():
    assert source_name(ROOT / "Vacation" / "a.jpg", ROOT) is None


def test_years_ago():
    assert years_ago(date(2023, 1, 3), date(2026, 1, 2)) == "2 years ago"
    assert years_ago(date(2023, 1, 3), date(2026, 1, 3)) == "3 years ago today"
    assert years_ago(date(2025, 1, 3), date(2026, 1, 3)) == "1 year ago today"
    assert years_ago(date(2026, 1, 3), date(2026, 10, 31)) is None


def test_date_line_defaults_to_weekday_and_years_ago_without_time():
    epoch = datetime(2023, 1, 3, 21, 17).timestamp()
    assert (
        date_line("January 3, 2023", epoch, "exif", date(2026, 10, 31))
        == "Tuesday, January 3, 2023 \u00b7 3 years ago"
    )


def test_date_line_options_toggle_each_part():
    epoch = datetime(2023, 1, 3, 21, 17).timestamp()
    today = date(2026, 10, 31)
    assert (
        date_line("January 3, 2023", epoch, "exif", today, show_time=True)
        == "Tuesday, January 3, 2023, 9:17 PM \u00b7 3 years ago"
    )
    assert (
        date_line(
            "January 3, 2023", epoch, "exif", today, show_weekday=False, show_years_ago=False
        )
        == "January 3, 2023"
    )


def test_date_line_omits_time_for_mtime_dates():
    epoch = datetime(2026, 3, 1, 0, 5).timestamp()
    assert date_line("March 1, 2026", epoch, "mtime", date(2026, 10, 31)) == "March 1, 2026"


def test_details_line():
    assert details_line("Charlottesville, Virginia", "Jason") == "Charlottesville, Virginia \u00b7 Jason"
    assert details_line(None, "Jason") == "Jason"
    assert details_line(None, None) is None


def test_gps_extracted_and_null_island_ignored():
    result = tags_to_result({"Composite:GPSLatitude": -40.83, "Composite:GPSLongitude": 172.88})
    assert (result.latitude, result.longitude) == (-40.83, 172.88)
    result = tags_to_result({"Composite:GPSLatitude": 0, "Composite:GPSLongitude": 0})
    assert result.latitude is None and result.longitude is None


def test_format_place():
    assert format_place({"name": "Charlottesville", "admin1": "Virginia"}) == "Charlottesville, Virginia"
    assert format_place({"name": "Paris", "admin1": ""}) == "Paris"
    assert format_place({"name": "Singapore", "admin1": "Singapore"}) == "Singapore"


def test_init_schema_upgrades_v1_database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # The current DDL minus the columns added since v1.
    v1_ddl = "\n".join(
        line for line in db._DDL.splitlines() if line.split()[:1] not in ([c] for c in db._ADDED_COLUMNS)
    )
    conn.executescript(v1_ddl)
    conn.execute("INSERT INTO app_state VALUES ('schema_version', '1')")
    conn.execute(
        "INSERT INTO photos (path, root_folder, size, mtime, content_hash, date_display, "
        "date_epoch, date_source, first_seen_at, last_scanned_at) "
        "VALUES ('/a.jpg', '/', 1, 0, 'h', 'd', 0, 'exif', 0, 0)"
    )
    assert "location" not in {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    db.init_schema(conn)
    row = conn.execute("SELECT latitude, location, meta_version FROM photos").fetchone()
    assert (row["latitude"], row["location"], row["meta_version"]) == (None, None, 1)
    assert db.get_state(conn, "schema_version") == db.SCHEMA_VERSION
