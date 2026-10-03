import datetime
import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from salud_rag.ingest.medlineplus import (
    INDEX_URL,
    TopicsFileNotFoundError,
    download_latest_topics,
    find_latest_topics_zip,
)

FIXTURES = Path(__file__).parent / "fixtures"
ZIP_URL = "https://medlineplus.gov/xml/mplus_topics_compressed_2026-10-02.zip"
XML_BYTES = b'<?xml version="1.0"?><health-topics><title>Diabetes</title></health-topics>'
FIXED_NOW = datetime.datetime(2026, 10, 2, 12, 30, tzinfo=datetime.UTC)


def make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def make_fetch(zip_bytes: bytes) -> tuple[Callable[[str], bytes], list[str]]:
    responses = {
        INDEX_URL: (FIXTURES / "medlineplus_xml_index.html").read_bytes(),
        ZIP_URL: zip_bytes,
    }
    requested: list[str] = []

    def fetch(url: str) -> bytes:
        requested.append(url)
        return responses[url]

    return fetch, requested


def test_find_latest_topics_zip_picks_most_recent_date_from_real_index() -> None:
    index_html = (FIXTURES / "medlineplus_xml_index.html").read_text(encoding="utf-8")

    topics_file = find_latest_topics_zip(index_html)

    assert topics_file.file_date == datetime.date(2026, 10, 2)
    assert topics_file.url == "https://medlineplus.gov/xml/mplus_topics_compressed_2026-10-02.zip"
    assert topics_file.xml_filename == "mplus_topics_2026-10-02.xml"


def test_find_latest_topics_zip_ignores_group_and_uncompressed_links() -> None:
    index_html = """
    <a href="xml/mplus_topics_2026-10-03.xml">Topics XML</a>
    <a href="xml/mplus_topic_groups_2026-10-03.xml">Groups XML</a>
    <a href="xml/mplus_topics_compressed_2026-10-01.zip">Compressed</a>
    """

    topics_file = find_latest_topics_zip(index_html)

    assert topics_file.file_date == datetime.date(2026, 10, 1)
    assert topics_file.url == "https://medlineplus.gov/xml/mplus_topics_compressed_2026-10-01.zip"


def test_find_latest_topics_zip_raises_when_no_compressed_link() -> None:
    index_html = '<a href="xml/mplus_topics_2026-10-02.xml">Topics XML</a>'

    with pytest.raises(TopicsFileNotFoundError):
        find_latest_topics_zip(index_html)


def test_download_writes_extracted_xml_and_manifest(tmp_path: Path) -> None:
    fetch, _ = make_fetch(make_zip({"mplus_topics_2026-10-02.xml": XML_BYTES}))
    dest_dir = tmp_path / "raw" / "medlineplus"

    result = download_latest_topics(dest_dir, fetch=fetch, now=lambda: FIXED_NOW)

    assert result.skipped is False
    assert result.xml_path == dest_dir / "mplus_topics_2026-10-02.xml"
    assert result.xml_path.read_bytes() == XML_BYTES
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_url"] == ZIP_URL
    assert manifest["index_url"] == INDEX_URL
    assert manifest["file_date"] == "2026-10-02"
    assert manifest["xml_filename"] == "mplus_topics_2026-10-02.xml"
    assert manifest["sha256"] == hashlib.sha256(XML_BYTES).hexdigest()
    assert manifest["size_bytes"] == len(XML_BYTES)
    assert manifest["downloaded_at"] == "2026-10-02T12:30:00+00:00"
    assert manifest["attribution"] == "Source: MedlinePlus, National Library of Medicine"
    assert "public domain" in manifest["license_note"]
    assert list(dest_dir.glob("*.part")) == []


def test_second_download_skips_without_fetching_zip(tmp_path: Path) -> None:
    fetch, requested = make_fetch(make_zip({"mplus_topics_2026-10-02.xml": XML_BYTES}))
    first = download_latest_topics(tmp_path, fetch=fetch, now=lambda: FIXED_NOW)
    requested.clear()

    second = download_latest_topics(tmp_path, fetch=fetch, now=lambda: FIXED_NOW)

    assert second.skipped is True
    assert second.xml_path == first.xml_path
    assert second.manifest_path == first.manifest_path
    assert requested == [INDEX_URL]


@pytest.mark.parametrize(
    "members",
    [
        {"readme.txt": b"no xml here"},
        {"a.xml": XML_BYTES, "b.xml": XML_BYTES},
    ],
    ids=["no-xml-member", "two-xml-members"],
)
def test_download_rejects_zip_without_exactly_one_xml(
    tmp_path: Path, members: dict[str, bytes]
) -> None:
    fetch, _ = make_fetch(make_zip(members))

    with pytest.raises(ValueError, match="exactly one .xml"):
        download_latest_topics(tmp_path, fetch=fetch, now=lambda: FIXED_NOW)

    assert list(tmp_path.iterdir()) == []


def test_download_resumes_when_previous_run_left_xml_without_manifest(tmp_path: Path) -> None:
    fetch, requested = make_fetch(make_zip({"mplus_topics_2026-10-02.xml": XML_BYTES}))
    (tmp_path / "mplus_topics_2026-10-02.xml").write_bytes(XML_BYTES)

    result = download_latest_topics(tmp_path, fetch=fetch, now=lambda: FIXED_NOW)

    assert result.skipped is False
    assert requested == [INDEX_URL, ZIP_URL]
    assert result.xml_path.read_bytes() == XML_BYTES
    assert json.loads(result.manifest_path.read_text(encoding="utf-8"))["source_url"] == ZIP_URL


def test_successful_download_leaves_no_part_files(tmp_path: Path) -> None:
    fetch, _ = make_fetch(make_zip({"mplus_topics_2026-10-02.xml": XML_BYTES}))

    result = download_latest_topics(tmp_path, fetch=fetch, now=lambda: FIXED_NOW)

    assert list(tmp_path.glob("*.part")) == []
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        result.manifest_path.name,
        result.xml_path.name,
    ]
    json.loads(result.manifest_path.read_text(encoding="utf-8"))


def test_interrupted_manifest_write_is_not_treated_as_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetch, requested = make_fetch(make_zip({"mplus_topics_2026-10-02.xml": XML_BYTES}))
    original_write_bytes = Path.write_bytes
    original_write_text = Path.write_text

    def crash_midway_bytes(self: Path, data: bytes) -> int:
        if "manifest" in self.name:
            original_write_bytes(self, data[: len(data) // 2])
            raise OSError("simulated crash")
        return original_write_bytes(self, data)

    def crash_midway_text(self: Path, data: str, encoding: str | None = None) -> int:
        if "manifest" in self.name:
            original_write_text(self, data[: len(data) // 2], encoding=encoding)
            raise OSError("simulated crash")
        return original_write_text(self, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_bytes", crash_midway_bytes)
    monkeypatch.setattr(Path, "write_text", crash_midway_text)
    with pytest.raises(OSError, match="simulated crash"):
        download_latest_topics(tmp_path, fetch=fetch, now=lambda: FIXED_NOW)
    monkeypatch.undo()
    requested.clear()

    result = download_latest_topics(tmp_path, fetch=fetch, now=lambda: FIXED_NOW)

    assert result.skipped is False
    assert requested == [INDEX_URL, ZIP_URL]
    assert json.loads(result.manifest_path.read_text(encoding="utf-8"))["size_bytes"] == len(
        XML_BYTES
    )
