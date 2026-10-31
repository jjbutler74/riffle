from riffle.imaging.overlay import resolve_overlay_text


def test_date_only_when_no_title_or_description():
    result = resolve_overlay_text("Jan 1, 2020", None, None)
    assert result.date_text == "Jan 1, 2020"
    assert result.primary is None
    assert result.secondary is None


def test_title_and_description_shown_together_when_they_differ():
    result = resolve_overlay_text("Jan 1, 2020", "Grand Canyon", "A trip out west in 2019")
    assert result.primary == "Grand Canyon"
    assert result.secondary == "A trip out west in 2019"


def test_only_title_shown_once_when_no_description():
    result = resolve_overlay_text("Jan 1, 2020", "Grand Canyon", None)
    assert result.primary == "Grand Canyon"
    assert result.secondary is None


def test_only_description_shown_once_when_no_title():
    result = resolve_overlay_text("Jan 1, 2020", None, "A trip out west")
    assert result.primary == "A trip out west"
    assert result.secondary is None


def test_matching_title_and_description_shown_once_case_insensitive():
    result = resolve_overlay_text("Jan 1, 2020", "Grand Canyon", "GRAND CANYON")
    assert result.primary == "Grand Canyon"
    assert result.secondary is None


def test_matching_title_and_description_shown_once_whitespace_normalized():
    result = resolve_overlay_text("Jan 1, 2020", "Grand   Canyon", "Grand Canyon")
    assert result.primary == "Grand   Canyon"
    assert result.secondary is None


def test_displayed_text_is_original_not_normalized():
    # Even though comparison is case/whitespace-insensitive, the retained
    # text must be the original un-normalized string (title wins as primary).
    result = resolve_overlay_text("Jan 1, 2020", "  Grand Canyon  ", "grand canyon")
    assert result.primary == "Grand Canyon"


def test_blank_strings_treated_as_absent():
    result = resolve_overlay_text("Jan 1, 2020", "   ", "")
    assert result.primary is None
    assert result.secondary is None


def test_caption_wraps_between_segments_not_inside_them():
    from riffle.imaging.overlay import _load_font, _wrap_segments

    font = _load_font(27)
    text = "Tuesday, January 3, 2023, 9:17 PM · 3 years ago"
    narrow = int(font.getlength("Tuesday, January 3, 2023, 9:17 PM")) + 5
    assert _wrap_segments(text, font, narrow, max_lines=2) == [
        "Tuesday, January 3, 2023, 9:17 PM",
        "3 years ago",
    ]
    assert _wrap_segments(text, font, 10_000, max_lines=2) == [text]
