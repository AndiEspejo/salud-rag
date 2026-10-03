import datetime
import io
import json
from pathlib import Path

import pytest

from salud_rag.ingest.medlineplus_topics import find_latest_manifest, html_to_text, parse_topics

FIXTURE = Path(__file__).parent / "fixtures" / "medlineplus_topics_sample.xml"


def _by_id(result):
    return {topic.topic_id: topic for topic in result.topics}


def test_fixture_parses_four_topics_and_skips_the_one_without_summary():
    result = parse_topics(FIXTURE)

    assert sorted(topic.topic_id for topic in result.topics) == [122, 529, 1882, 2238]
    assert len(result.skipped) == 1
    skipped_id, reason = result.skipped[0]
    assert skipped_id == 2245
    assert "summary" in reason


def test_topic_metadata_is_read_from_attributes_and_children():
    topic = _by_id(parse_topics(FIXTURE))[2238]

    assert topic.language == "Spanish"
    assert topic.title == "Aborto"
    assert topic.url == "https://medlineplus.gov/spanish/abortion.html"
    assert topic.date_created == datetime.date(2006, 10, 31)
    assert topic.meta_desc is not None
    assert topic.meta_desc.startswith("Un aborto es un procedimiento médico")
    assert "Aborto inducido" in topic.also_called
    assert len(topic.also_called) == 4
    assert topic.groups == ("Embarazo y reproducción", "Sistema reproductor femenino")
    assert topic.see_references == ("Embriotomía",)
    assert topic.summary_html.startswith("<p>Un aborto inducido")


def test_related_topic_ids_are_read():
    topic = _by_id(parse_topics(FIXTURE))[1882]

    assert topic.related_topic_ids == (1865,)


def test_spanish_and_english_topics_map_to_each_other():
    topics = _by_id(parse_topics(FIXTURE))

    assert topics[2238].mapped_topic_id == 122
    assert topics[2238].mapped_topic_url == "https://medlineplus.gov/abortion.html"
    assert topics[122].mapped_topic_id == 2238
    assert topics[122].language == "English"
    assert topics[529].mapped_topic_id == 1882


def test_third_party_site_content_is_ignored():
    result = parse_topics(FIXTURE)
    site_title = "Aborto médico"
    site_url = "mayoclinic.org"

    for topic in result.topics:
        for value in vars(topic).values():
            texts = value if isinstance(value, tuple) else (value,)
            for text in texts:
                if isinstance(text, str):
                    assert site_title not in text
                    assert site_url not in text


def test_parse_accepts_a_binary_stream():
    with FIXTURE.open("rb") as stream:
        result = parse_topics(stream)

    assert len(result.topics) == 4


def test_blank_full_summary_is_skipped():
    xml = (
        '<health-topics total="1"><health-topic title="Vacío" url="https://example.org/x" '
        'id="1" language="Spanish" date-created="01/02/2003">'
        "<full-summary>  \n </full-summary></health-topic></health-topics>"
    )

    result = parse_topics(io.BytesIO(xml.encode("utf-8")))

    assert result.topics == ()
    assert result.skipped == ((1, "blank full-summary"),)


def test_html_to_text_separates_paragraphs_and_lists_items_as_dash_lines():
    html = (
        "<p>First   paragraph\nwith  spaces.</p>\n"
        '<ul>\n  <li><a href="https://medlineplus.gov/x.html">Linked item</a></li>\n'
        "  <li>Plain item</li>\n</ul>\n"
        "<p>Second paragraph.<br>After break.</p>"
    )

    assert html_to_text(html) == (
        "First paragraph with spaces.\n\n"
        "- Linked item\n"
        "- Plain item\n\n"
        "Second paragraph.\n"
        "After break."
    )


def test_html_to_text_drops_hrefs_and_unescapes_entities():
    text = html_to_text('<p>Salud &amp; bienestar: <a href="https://x.org/a">m&aacute;s</a> ñ</p>')

    assert text == "Salud & bienestar: más ñ"
    assert "http" not in text
    assert "<" not in text


def test_html_to_text_handles_headings_and_collapses_blank_lines():
    text = html_to_text("<h2>Title</h2>\n\n\n<div><p>Body</p></div>\n")

    assert text == "Title\n\nBody"


def test_html_to_text_keeps_nested_list_items_contiguous():
    html = "<ul><li>Outer:<ul><li>Inner one</li><li>Inner two</li></ul></li><li>Next</li></ul>"

    assert html_to_text(html) == "- Outer:\n- Inner one\n- Inner two\n- Next"


def test_real_fixture_summaries_contain_no_markup():
    for topic in parse_topics(FIXTURE).topics:
        assert "<" not in topic.summary_text
        assert "http" not in topic.summary_text
        assert topic.summary_text == topic.summary_text.strip()
        assert "\n\n\n" not in topic.summary_text


def _write_download(directory: Path, file_date: str, *, with_xml: bool = True) -> None:
    xml_filename = f"mplus_topics_{file_date}.xml"
    manifest = {"file_date": file_date, "xml_filename": xml_filename, "sha256": "abc"}
    (directory / f"mplus_topics_{file_date}.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    if with_xml:
        (directory / xml_filename).write_text("<health-topics/>", encoding="utf-8")


def test_find_latest_manifest_picks_the_newest_file_date(tmp_path):
    _write_download(tmp_path, "2026-09-30")
    _write_download(tmp_path, "2026-10-02")

    manifest = find_latest_manifest(tmp_path)

    assert manifest["file_date"] == "2026-10-02"
    assert manifest["xml_filename"] == "mplus_topics_2026-10-02.xml"


def test_find_latest_manifest_raises_when_there_are_no_manifests(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_latest_manifest(tmp_path)


def test_find_latest_manifest_raises_when_the_xml_is_missing(tmp_path):
    _write_download(tmp_path, "2026-10-02", with_xml=False)

    with pytest.raises(FileNotFoundError, match="mplus_topics_2026-10-02.xml"):
        find_latest_manifest(tmp_path)
