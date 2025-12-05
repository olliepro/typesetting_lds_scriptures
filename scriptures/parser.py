"""
Parsing helpers that convert scraper JSON into typed chapter objects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from .cleaning import clean_text, normalize_whitespace
from .models import Chapter, FootnoteEntry, FootnoteLink, Verse


_WORK_SEGMENT_TO_SLUG = {
    "ot": "old-testament",
    "nt": "new-testament",
    "bofm": "book-of-mormon",
    "dc-testament": "doctrine-and-covenants",
    "pgp": "pearl-of-great-price",
    "jst": "jst-appendix",
}

_SMALL_TAG_REPLACEMENT = '<font size="7">{}</font> '


def _unwrap_footnote_links(html: str) -> str:
    """Replace anchor-based footnote markers with plain superscripts."""

    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select("a.footnote-link"):
        sup = anchor.find("sup")
        letter = sup.get("data-value") if sup else ""
        if sup:
            sup.decompose()
        # Add a leading space before the footnote marker when stuck to a word
        needs_space = False
        prev = anchor.previous_element
        skipped_ws = []
        while prev and isinstance(prev, NavigableString) and not str(prev).strip():
            skipped_ws.append(prev)
            prev = prev.previous_element
        if isinstance(prev, NavigableString):
            text = str(prev)
            needs_space = bool(text) and not text[-1].isspace()
        elif prev and getattr(prev, "name", None):
            needs_space = True

        new_sup = soup.new_tag("sup")
        new_sup.string = letter
        if needs_space:
            for ws in skipped_ws:
                ws.extract()
            anchor.insert_before(
                "\u00a0"
            )  # non‑breaking space to preserve gap in ReportLab
        anchor.insert_before(new_sup)
        for child in list(anchor.children):
            anchor.insert_before(child)
        anchor.decompose()
    return soup.decode_contents()


def _normalize_inline_html(fragment: Tag | NavigableString) -> str:
    """Convert a BeautifulSoup fragment into ReportLab-friendly markup."""

    if isinstance(fragment, NavigableString):
        return clean_text(str(fragment))

    if fragment.name == "small":
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return _SMALL_TAG_REPLACEMENT.format(inner)

    if fragment.name in {"em", "i"}:
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return f"<i>{inner}</i>"

    if fragment.name in {"strong", "b"}:
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return f"<b>{inner}</b>"

    if fragment.name == "sup":
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return f"<sup>{inner}</sup>"

    if fragment.name == "a":
        href = fragment.get("href", "")
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return f'<a href="{href}">{inner}</a>'

    return "".join(_normalize_inline_html(child) for child in fragment.children)


def _parse_footnote_links(node: Tag, current_work: str) -> List[FootnoteLink]:
    """Extract FootnoteLink objects from a footnote <li> element."""

    links: List[FootnoteLink] = []
    for anchor in node.find_all("a", href=True):
        href = anchor["href"]
        parsed = urlparse(href)
        slug = ""
        path_parts = [p for p in parsed.path.split("/") if p]
        if (
            len(path_parts) >= 3
            and path_parts[0] == "study"
            and path_parts[1] == "scriptures"
        ):
            slug = _WORK_SEGMENT_TO_SLUG.get(path_parts[2], "")
        links.append(
            FootnoteLink(
                text=normalize_whitespace(anchor.get_text(strip=True)),
                href=href,
                is_internal=slug == current_work,
            )
        )
    return links


def _parse_footnotes(
    html: str, current_work: str, chapter_number: str
) -> List[FootnoteEntry]:
    """Parse the nested footnote list into FootnoteEntry objects."""

    soup = BeautifulSoup(html, "html.parser")
    entries: List[FootnoteEntry] = []

    def split_segments(li: Tag) -> List[str]:
        """Split a footnote <li> into display-ready segments without touching hrefs."""

        tokens: List[str | Tag] = []
        for child in li.children:
            if isinstance(child, NavigableString):
                parts = re.split(r"(;)", str(child))
                tokens.extend([p for p in parts if p != ""])
            else:
                tokens.append(child)

        segments: List[str] = []
        buffer: List[str] = []
        for idx, tok in enumerate(tokens):
            if tok == ";":
                j = idx + 1
                while (
                    j < len(tokens)
                    and isinstance(tokens[j], str)
                    and tokens[j].strip() == ""
                ):
                    j += 1
                next_tok = tokens[j] if j < len(tokens) else None
                has_alpha = False
                if isinstance(next_tok, str):
                    plain = re.sub(r"<[^>]+>", "", next_tok).strip()
                    has_alpha = bool(re.search(r"[A-Za-z]", plain))
                elif next_tok is not None:
                    text = next_tok.get_text(strip=True)
                    has_alpha = bool(re.search(r"[A-Za-z]", text))
                if has_alpha:
                    buffer.append(";")
                    segments.append("".join(buffer).strip())
                    buffer = []
                else:
                    buffer.append("; ")
            else:
                if isinstance(tok, str):
                    rendered = clean_text(tok)
                else:
                    rendered = _normalize_inline_html(tok)

                plain = re.sub(r"<[^>]+>", "", rendered).strip()
                current = "".join(buffer)
                needs_new_line_for_tg = buffer and re.match(r"TG\b", plain)
                needs_new_line_after_period = (
                    buffer
                    and current.rstrip().endswith(".")
                    and not current.rstrip().endswith(". ")
                    and isinstance(tok, Tag)
                )

                if needs_new_line_for_tg or needs_new_line_after_period:
                    segments.append(current.strip())
                    buffer = [rendered]
                else:
                    buffer.append(rendered)
        if buffer:
            segments.append("".join(buffer).strip())
        return [seg for seg in segments if seg]

    for verse_node in soup.find_all("li", attrs={"data-marker": True}):
        verse = verse_node["data-marker"]
        inner_list = verse_node.find("ul")
        if not inner_list:
            continue
        for li in inner_list.find_all("li", attrs={"data-full-marker": True}):
            letter = li.get("data-marker", "")
            text_markup = _normalize_inline_html(li)
            segments = split_segments(li)
            entry = FootnoteEntry(
                chapter=chapter_number,
                verse=verse,
                letter=letter,
                text=text_markup,
                segments=segments if segments else [text_markup],
                links=_parse_footnote_links(li, current_work),
            )
            entries.append(entry)
    return entries


def _parse_verse(paragraph: dict) -> Verse:
    """Convert a verse paragraph dictionary into a Verse instance."""

    raw_html = paragraph["contentHtml"]
    clean_html = _unwrap_footnote_links(raw_html)
    plain = clean_text(BeautifulSoup(clean_html, "html.parser").get_text(" "))
    return Verse(
        chapter="",
        number=paragraph.get("number", ""),
        html=clean_html,
        plain_text=plain,
        compare_id=paragraph.get("compareId", ""),
    )


def _header_blocks(paragraphs: Iterable[dict]) -> List[tuple[str, str]]:
    """Collect header-like paragraph fragments in order."""

    header_types = {"book-title", "chapter-title"}
    return [
        (p["type"], p["contentHtml"]) for p in paragraphs if p["type"] in header_types
    ]


def _standard_work_from_path(path: Path) -> str:
    """Infer the standard work slug from a chapter path."""

    return path.parent.parent.name


def load_chapter(path: Path) -> Chapter:
    """Load a single scraped JSON chapter file into a Chapter object.

    Example:
        >>> _ = load_chapter(Path('external/python-scripture-scraper/_output/en-json/new-testament/matthew/matthew-1.json'))  # doctest: +SKIP
    """

    data = json.loads(path.read_text())
    paragraphs: List[dict] = data["paragraphs"]
    standard_work = _standard_work_from_path(path)
    book_slug = path.parent.name
    chapter_number = data.get("number", path.stem.split("-")[-1])

    verses: List[Verse] = []
    footnotes: List[FootnoteEntry] = []
    for p in paragraphs:
        if p["type"] == "verse":
            verse = _parse_verse(p)
            verse.chapter = chapter_number
            verses.append(verse)
        elif p["type"] == "study-footnotes":
            footnotes.extend(
                _parse_footnotes(p["contentHtml"], standard_work, chapter_number)
            )

    title = data.get("name", f"{book_slug} {chapter_number}")
    return Chapter(
        standard_work=standard_work,
        book=book_slug,
        abbrev=data.get("abbrev"),
        number=chapter_number,
        title=title,
        header_blocks=_header_blocks(paragraphs),
        paragraphs=paragraphs,
        verses=verses,
        footnotes=footnotes,
        source_path=path,
    )
