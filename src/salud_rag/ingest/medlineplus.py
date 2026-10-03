"""Download the latest MedlinePlus health topics XML."""

import datetime
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

INDEX_URL = "https://medlineplus.gov/xml.html"
ATTRIBUTION = "Source: MedlinePlus, National Library of Medicine"
LICENSE_NOTE = (
    "Health topic summaries are public domain. Copyrighted content (A.D.A.M. Medical "
    "Encyclopedia, ASHP drug information, most images) must be filtered before use."
)
USER_AGENT = "salud-rag/0.1 (+portfolio project)"

_TOPICS_ZIP_HREF = re.compile(
    r"""href=["']([^"']*mplus_topics_compressed_(\d{4}-\d{2}-\d{2})\.zip)["']"""
)

Fetch = Callable[[str], bytes]


class TopicsFileNotFoundError(Exception):
    """The index page has no compressed health topics XML link."""


@dataclass(frozen=True)
class TopicsFile:
    url: str
    file_date: datetime.date

    @property
    def xml_filename(self) -> str:
        return f"mplus_topics_{self.file_date.isoformat()}.xml"

    @property
    def manifest_filename(self) -> str:
        return f"mplus_topics_{self.file_date.isoformat()}.manifest.json"


@dataclass(frozen=True)
class DownloadResult:
    topics_file: TopicsFile
    xml_path: Path
    manifest_path: Path
    skipped: bool


def find_latest_topics_zip(index_html: str, base_url: str = INDEX_URL) -> TopicsFile:
    candidates = [
        TopicsFile(url=urljoin(base_url, href), file_date=datetime.date.fromisoformat(day))
        for href, day in _TOPICS_ZIP_HREF.findall(index_html)
    ]
    if not candidates:
        raise TopicsFileNotFoundError("No mplus_topics_compressed_YYYY-MM-DD.zip link found")
    return max(candidates, key=lambda topics_file: topics_file.file_date)


def fetch_url(url: str, timeout: float = 60.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _extract_single_xml(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        xml_members = [name for name in archive.namelist() if name.endswith(".xml")]
        if len(xml_members) != 1:
            raise ValueError(
                f"Expected exactly one .xml member in topics zip, found {len(xml_members)}: "
                f"{xml_members}"
            )
        return archive.read(xml_members[0])


def download_latest_topics(
    dest_dir: Path,
    fetch: Fetch = fetch_url,
    now: Callable[[], datetime.datetime] = _utc_now,
) -> DownloadResult:
    topics_file = find_latest_topics_zip(fetch(INDEX_URL).decode("utf-8"))
    xml_path = dest_dir / topics_file.xml_filename
    manifest_path = dest_dir / topics_file.manifest_filename
    if xml_path.exists() and manifest_path.exists():
        return DownloadResult(topics_file, xml_path, manifest_path, skipped=True)

    dest_dir.mkdir(parents=True, exist_ok=True)
    xml_bytes = _extract_single_xml(fetch(topics_file.url))

    part_path = xml_path.with_name(xml_path.name + ".part")
    part_path.write_bytes(xml_bytes)
    part_path.replace(xml_path)

    manifest = {
        "source_url": topics_file.url,
        "index_url": INDEX_URL,
        "file_date": topics_file.file_date.isoformat(),
        "xml_filename": topics_file.xml_filename,
        "sha256": hashlib.sha256(xml_bytes).hexdigest(),
        "size_bytes": len(xml_bytes),
        "downloaded_at": now().astimezone(datetime.UTC).isoformat(),
        "attribution": ATTRIBUTION,
        "license_note": LICENSE_NOTE,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return DownloadResult(topics_file, xml_path, manifest_path, skipped=False)
