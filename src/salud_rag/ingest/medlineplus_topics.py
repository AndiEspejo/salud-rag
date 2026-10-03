"""Parse the MedlinePlus health topics XML into plain records."""

import datetime
import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import BinaryIO

LICENSE = "public-domain"

_DATE_FORMAT = "%m/%d/%Y"
_BLOCK_TAGS = frozenset({"p", "div", "h1", "h2", "h3", "h4", "h5", "h6"})
_LIST_TAGS = frozenset({"ul", "ol"})


@dataclass(frozen=True)
class Topic:
    topic_id: int
    language: str
    title: str
    url: str
    date_created: datetime.date
    meta_desc: str | None
    also_called: tuple[str, ...]
    see_references: tuple[str, ...]
    groups: tuple[str, ...]
    related_topic_ids: tuple[int, ...]
    mapped_topic_id: int | None
    mapped_topic_url: str | None
    summary_html: str
    summary_text: str


@dataclass(frozen=True)
class ParseResult:
    topics: tuple[Topic, ...]
    skipped: tuple[tuple[int, str], ...]


class _TextExtractor(HTMLParser):
    """Collects text lines: blocks become paragraphs, list items become "- " lines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._current: list[str] = []
        self._list_depth = 0
        self._list_item_depth = 0
        self._blank_pending = False

    def _end_line(self) -> None:
        text = " ".join("".join(self._current).split())
        self._current = []
        if not text:
            return
        if self._blank_pending and self.lines:
            self.lines.append("")
        self._blank_pending = False
        self.lines.append(f"- {text}" if self._list_item_depth else text)

    def _end_paragraph(self) -> None:
        self._end_line()
        self._blank_pending = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self._end_paragraph()
        elif tag in _LIST_TAGS:
            if self._list_depth:
                self._end_line()
            else:
                self._end_paragraph()
            self._list_depth += 1
        elif tag == "li":
            self._end_line()
            # `</li>` is optional in HTML, so an `<li>` never nests deeper than its list.
            self._list_item_depth = min(self._list_item_depth + 1, max(self._list_depth, 1))
        elif tag == "br":
            self._end_line()

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._end_paragraph()
        elif tag in _LIST_TAGS:
            self._end_line()
            self._list_depth = max(self._list_depth - 1, 0)
            # Closing a list implicitly closes any `<li>` left open inside it.
            self._list_item_depth = min(self._list_item_depth, self._list_depth)
            if not self._list_depth:
                self._end_paragraph()
        elif tag == "li":
            self._end_line()
            self._list_item_depth = max(self._list_item_depth - 1, 0)

    def handle_data(self, data: str) -> None:
        self._current.append(data)

    def finish(self) -> str:
        self.close()
        self._end_line()
        return "\n".join(self.lines)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.finish()


def _parse_date(value: str) -> datetime.date:
    return datetime.datetime.strptime(value, _DATE_FORMAT).date()


def _texts(element: ET.Element, tag: str) -> tuple[str, ...]:
    return tuple((child.text or "").strip() for child in element.findall(tag))


def _build_topic(element: ET.Element, summary_html: str) -> Topic:
    mapped = element.find("language-mapped-topic")
    return Topic(
        topic_id=int(element.attrib["id"]),
        language=element.attrib["language"],
        title=element.attrib["title"],
        url=element.attrib["url"],
        date_created=_parse_date(element.attrib["date-created"]),
        meta_desc=element.attrib.get("meta-desc"),
        also_called=_texts(element, "also-called"),
        see_references=_texts(element, "see-reference"),
        groups=_texts(element, "group"),
        related_topic_ids=tuple(int(t.attrib["id"]) for t in element.findall("related-topic")),
        mapped_topic_id=int(mapped.attrib["id"]) if mapped is not None else None,
        mapped_topic_url=mapped.attrib["url"] if mapped is not None else None,
        summary_html=summary_html,
        summary_text=html_to_text(summary_html),
    )


def parse_topics(source: str | Path | BinaryIO) -> ParseResult:
    topics: list[Topic] = []
    skipped: list[tuple[int, str]] = []
    for _, element in ET.iterparse(source, events=("end",)):
        if element.tag != "health-topic":
            continue
        summary = element.find("full-summary")
        if summary is None:
            skipped.append((int(element.attrib["id"]), "missing full-summary"))
        elif not (summary.text or "").strip():
            skipped.append((int(element.attrib["id"]), "blank full-summary"))
        else:
            topics.append(_build_topic(element, summary.text or ""))
        element.clear()
    return ParseResult(topics=tuple(topics), skipped=tuple(skipped))


def find_latest_manifest(dest_dir: Path) -> dict:
    manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in dest_dir.glob("mplus_topics_*.manifest.json")
    ]
    if not manifests:
        raise FileNotFoundError(f"No mplus_topics_*.manifest.json found in {dest_dir}")
    latest = max(manifests, key=lambda manifest: manifest["file_date"])
    xml_path = dest_dir / latest["xml_filename"]
    if not xml_path.exists():
        raise FileNotFoundError(f"Manifest names {xml_path.name} but it is missing in {dest_dir}")
    return latest


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest_sha256(manifest: dict, raw_dir: Path) -> Path:
    xml_path = raw_dir / manifest["xml_filename"]
    expected = manifest["sha256"]
    actual = file_sha256(xml_path)
    if actual != expected:
        raise ValueError(
            f"SHA-256 mismatch for {xml_path.name}: "
            f"manifest {expected[:12]}..., file {actual[:12]}..."
        )
    return xml_path
