from riffle.scan.exif import (
    extract_description,
    extract_title,
    is_camera_boilerplate,
    tags_to_result,
)


def test_camera_boilerplate_descriptions_detected():
    for text in [
        r"DCIM\101GOPRO",
        r"DCIM\105GOPRO",
        "OLYMPUS DIGITAL CAMERA         ",
        "DCF 1.0",
        "  (C) 2003 Gateway,Inc.        ",
        "SONY DSC",
    ]:
        assert is_camera_boilerplate(text), text
    for text in ["Looking good", "Cheese", "GoPro fun", "DCIM photos from the trip"]:
        assert not is_camera_boilerplate(text), text


def test_filenames_timestamps_and_chipset_names_are_placeholders():
    for text in [
        "MVI_2731",
        "IMG_1234.JPG",
        "DSC01234",
        "PXL_20230101_120000123",
        "20250201_135158",
        "4/6/2003 12:21 PM",
        "2003-04-06",
        "NOVATEK CAMERA",
        "SAMSUNG CAMERA PICTURES",
    ]:
        assert is_camera_boilerplate(text), text
    for text in ["Pip at 3", "Img of the day", "Run!", "Riley's turn", "Christmas 2019"]:
        assert not is_camera_boilerplate(text), text


def test_camera_make_and_model_are_placeholders():
    assert is_camera_boilerplate("Canon PowerShot SD1000", make="Canon", model="Canon PowerShot SD1000")
    assert is_camera_boilerplate("NIKON  COOLPIX P900", make="NIKON", model="COOLPIX P900")
    assert not is_camera_boilerplate("Canon at the beach", make="Canon", model="EOS R6")
    tags = {"EXIF:Make": "HONOR", "EXIF:Model": "PCT-L29", "EXIF:ImageDescription": "PCT-L29"}
    assert extract_description(tags) is None


def test_user_ignore_patterns():
    patterns = ["HONOR camera", "Photo by *"]
    assert is_camera_boilerplate("honor   CAMERA", patterns)
    assert is_camera_boilerplate("Photo by Grandma", patterns)
    assert not is_camera_boilerplate("A photo by the lake", patterns)
    tags = {"XMP:Title": "Photo by Bob", "EXIF:XPTitle": "Sunset"}
    assert extract_title(tags, patterns) == "Sunset"


def test_description_skips_boilerplate_for_a_real_one():
    tags = {"XMP:Description": "SONY DSC", "EXIF:ImageDescription": "Beach day"}
    assert extract_description(tags) == "Beach day"
    assert extract_description({"EXIF:ImageDescription": r"DCIM\100GOPRO"}) is None


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
