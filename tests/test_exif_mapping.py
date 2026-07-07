from riffle.scan.exif import extract_description, extract_title, tags_to_result


def test_title_prefers_xmp_dc_title():
    tags = {
        "XMP:Title": "Sunset",
        "IPTC:ObjectName": "IPTC Name",
        "EXIF:XPTitle": "XP Title",
    }
    assert extract_title(tags) == "Sunset"


def test_title_falls_back_to_iptc_object_name():
    tags = {"IPTC:ObjectName": "IPTC Name", "EXIF:XPTitle": "XP Title"}
    assert extract_title(tags) == "IPTC Name"


def test_title_falls_back_to_exif_xptitle():
    tags = {"EXIF:XPTitle": "XP Title"}
    assert extract_title(tags) == "XP Title"


def test_title_none_when_no_candidates():
    assert extract_title({}) is None
    assert extract_title({"XMP:Title": "   "}) is None


def test_description_priority_chain():
    assert extract_description({"XMP:Description": "A"}) == "A"
    assert extract_description({"IPTC:Caption-Abstract": "B"}) == "B"
    assert extract_description({"EXIF:ImageDescription": "C"}) == "C"
    assert (
        extract_description(
            {
                "XMP:Description": "A",
                "IPTC:Caption-Abstract": "B",
                "EXIF:ImageDescription": "C",
            }
        )
        == "A"
    )


def test_description_none_when_no_candidates():
    assert extract_description({}) is None


def test_tags_to_result_combines_all_fields():
    tags = {
        "XMP:Title": "Sunset",
        "EXIF:ImageDescription": "Nice evening",
        "EXIF:DateTimeOriginal": "2020:05:04 12:33:01",
    }
    result = tags_to_result(tags)
    assert result.title == "Sunset"
    assert result.description == "Nice evening"
    assert result.date_original == "2020:05:04 12:33:01"


def test_tags_to_result_ignores_zeroed_date():
    tags = {"EXIF:DateTimeOriginal": "0000:00:00 00:00:00"}
    result = tags_to_result(tags)
    assert result.date_original is None
