"""
Build a debug PDF comparing single-paragraph vs per-line rendering
for the entire Doctrine and Covenants section 84.

Output: ``output/debug-wrap-section84.pdf``
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List
import re
import sys

from reportlab.lib import colors
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pyphen import Pyphen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scriptures.models import Book, Chapter
from scriptures.parser import load_chapter
from scriptures.pdf_builder import (
    PageSettings,
    _line_fragments,
    _paragraph_from_html,
    _verse_markup,
    build_styles,
    register_palatino,
)


def _chunk_lines(lines: List[str], size: int) -> Iterable[List[str]]:
    """Yield line chunks of at most ``size`` items each."""

    for start in range(0, len(lines), size):
        yield lines[start : start + size]


def _load_section_84() -> Chapter:
    """Return Chapter object for D&C 84 from the raw JSON file."""

    path = Path("data/raw/doctrine-and-covenants/sections/section-84.json")
    chapter = load_chapter(path)
    book = Book(
        standard_work=chapter.standard_work,
        name="Doctrine and Covenants",
        slug="sections",
        abbrev="D&C",
        chapters=[chapter],
    )
    chapter.book = book.slug
    return chapter


_TRAILING_BR_RE = re.compile(r"(?:<br\\s*/?>)+\\s*$", re.IGNORECASE)


def _strip_trailing_breaks(html: str) -> str:
    """Remove trailing <br/> runs so we don't double-insert stanza gaps."""

    return _TRAILING_BR_RE.sub("", html)


def _build_story(chunk_lines: List[str], idx: int, styles, settings: PageSettings):
    """Create a two-column comparison table for one chunk of lines."""

    col_width = settings.text_column_width()
    left_html = "<br/>".join(chunk_lines)
    left_para = Paragraph(left_html, styles["body"])

    per_line_paras = []
    for line_idx, html in enumerate(chunk_lines):
        style = styles["body"] if line_idx == 0 and idx == 0 else styles["body-cont"]
        per_line_paras.append(Paragraph(html, style))

    table = Table(
        [
            [
                Paragraph(f"Chunk {idx+1}: single paragraph", styles["preface"]),
                Paragraph(f"Chunk {idx+1}: per-line paragraphs", styles["preface"]),
            ],
            [left_para, per_line_paras],
        ],
        colWidths=[col_width, col_width],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBEFORE", (1, 0), (1, 1), 0.4, colors.lightgrey),
            ]
        )
    )
    return [Spacer(1, 6), table]


def main() -> None:
    """Render output/debug-wrap-section84.pdf.

    Example:
        >>> main()  # doctest: +SKIP
    """

    chapter = _load_section_84()
    settings = PageSettings()
    font = register_palatino()
    styles = build_styles(font)
    hyphenator = Pyphen(lang="en_US")

    # Build one big Paragraph and split into wrapped lines at column width.
    verse_blocks = []
    for v in chapter.verses:
        cleaned = _strip_trailing_breaks(v.html)
        # Recreate the verse markup without trailing <br/> runs.
        verse_blocks.append(f"<b>{v.number}</b>&nbsp;{cleaned}")
    full_html = "<br/><br/>".join(verse_blocks)
    base_para = _paragraph_from_html(full_html, styles["body"], hyphenator)
    line_htmls = _line_fragments(base_para, settings.text_column_width())

    doc = SimpleDocTemplate(
        str(Path("output/debug-wrap-section84.pdf")),
        pagesize=(settings.page_width, settings.page_height),
        leftMargin=settings.margin_left,
        rightMargin=settings.margin_right,
        topMargin=settings.margin_top,
        bottomMargin=settings.margin_bottom,
    )

    story: List = []
    for idx, chunk in enumerate(_chunk_lines(line_htmls, 20)):
        story.extend(_build_story(chunk, idx, styles, settings))

    doc.build(story)


if __name__ == "__main__":
    main()
