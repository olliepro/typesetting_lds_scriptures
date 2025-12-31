"""Identify lines with the largest whitespace stretch from justification."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from bs4 import BeautifulSoup, NavigableString, Tag
from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scriptures.ingest import build_corpus
from scriptures.models import Book, Chapter, StandardWork
from scriptures.pdf.pdf_settings import PageSettings, build_styles, register_palatino
from scriptures.pdf.pdf_text import _line_items_for_chapter
from scriptures.pdf.pdf_text_html import _wrap_paragraph
from scriptures.pdf.pdf_text_line_helpers import _group_lines, _paragraph_sources_from_group
from scriptures.pdf.pdf_types import FlowItem

FIRST_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


@dataclass(slots=True)
class FontContext:
    """Prepared font, style, and width settings for scanning.

    Args:
        settings: PageSettings with font names populated.
        styles: ParagraphStyle lookup for rendering.
        hyphenator: Pyphen instance for hyphenation.
        column_width: Column width used for verse wrapping.
        body_width: Full-width text width.
    """

    settings: PageSettings
    styles: dict[str, ParagraphStyle]
    hyphenator: Pyphen
    column_width: float
    body_width: float


@dataclass(slots=True)
class SegmentLocation:
    """Identifying metadata for a paragraph/verse segment.

    Args:
        book_name: Human-readable book name.
        chapter: Chapter identifier.
        verse: Verse identifier, if present.
        segment_type: "verse" or "study".
    """

    book_name: str
    chapter: str
    verse: str | None
    segment_type: str

    @classmethod
    def from_item(cls, *, item: FlowItem) -> "SegmentLocation":
        """Create a location from a FlowItem.

        Args:
            item: FlowItem containing provenance metadata.
        Returns:
            SegmentLocation instance.
        """

        segment_type = "verse" if item.is_verse else "study"
        return cls(
            book_name=item.book_name,
            chapter=item.chapter,
            verse=item.verse,
            segment_type=segment_type,
        )


@dataclass(slots=True)
class StretchLine:
    """Line stretch metadata for a wrapped paragraph line.

    Args:
        location: SegmentLocation metadata.
        line_index: 1-based line index within the paragraph.
        line_count: Total line count for the paragraph.
        stretch_per_space: Extra space per word gap.
        extra_space: Total extra space distributed in the line.
        word_count: Word count in the line.
        next_first_word_raw: First word of the following line (raw).
        next_first_word_clean: First word after stripping superscript prefix.
        sup_prefix: Superscript prefix letter when present.
    """

    location: SegmentLocation
    line_index: int
    line_count: int
    stretch_per_space: float
    extra_space: float
    word_count: int
    next_first_word_raw: str
    next_first_word_clean: str
    sup_prefix: str

    def tsv_row(self) -> str:
        """Return a TSV row for the line stretch.

        Returns:
            Tab-separated string with stretch metadata.
        """

        values = [
            self.location.book_name,
            self.location.chapter,
            self.location.verse or "",
            self.location.segment_type,
            str(self.line_index),
            str(self.line_count),
            f"{self.stretch_per_space:.3f}",
            f"{self.extra_space:.3f}",
            str(self.word_count),
            self.next_first_word_raw,
            self.next_first_word_clean,
            self.sup_prefix,
        ]
        return "\t".join(values)


def _parse_args() -> argparse.Namespace:
    """Return CLI arguments for the justification stretch scanner.

    Returns:
        argparse.Namespace of parsed CLI args.
    """

    parser = argparse.ArgumentParser(
        description="Find lines with the largest whitespace stretch from justification."
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw"),
        help="Root directory containing raw scripture data.",
    )
    parser.add_argument(
        "--metadata-path",
        type=Path,
        default=Path("data/raw/metadata-scriptures.json"),
        help="Metadata JSON path.",
    )
    parser.add_argument(
        "--max-chapters",
        type=int,
        default=None,
        help="Optional cap on chapters per book.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of top lines to output.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("output/justification_stretch_top20.tsv"),
        help="Output TSV path.",
    )
    return parser.parse_args()


def _setup_context() -> FontContext:
    """Return prepared font/style context for scanning.

    Returns:
        FontContext containing styles, hyphenator, and widths.
    """

    settings = PageSettings()
    font_name = register_palatino()
    settings.font_name = font_name
    settings.font_bold_name = "Palatino-Bold"
    styles = build_styles(font_name)
    column_width = settings.text_column_width() - settings.column_gap / 2
    return FontContext(
        settings=settings,
        styles=styles,
        hyphenator=Pyphen(lang="en_US"),
        column_width=column_width,
        body_width=settings.body_width,
    )


def _iter_chapters(
    *, corpus: Sequence[StandardWork]
) -> Iterable[tuple[StandardWork, Book, Chapter, int]]:
    """Yield chapters with their parent work, book, and index.

    Args:
        corpus: Standard works to scan.
    Returns:
        Iterable of (work, book, chapter, chapter_index) tuples.
    """

    for work in corpus:
        for book in work.books:
            for idx, chapter in enumerate(book.chapters):
                yield work, book, chapter, idx


def _chapter_items(
    *,
    chapter: Chapter,
    book: Book,
    chapter_index: int,
    context: FontContext,
) -> list[FlowItem]:
    """Return line items for a chapter using PDF wrap settings.

    Args:
        chapter: Chapter to render.
        book: Book containing the chapter.
        chapter_index: Index of the chapter within the book.
        context: Font context for wrapping.
    Returns:
        List of FlowItems for the chapter.
    """

    is_dc = book.standard_work == "doctrine-and-covenants"
    return _line_items_for_chapter(
        chapter=chapter,
        book=book,
        styles=context.styles,
        hyphenator=context.hyphenator,
        column_width=context.column_width,
        body_width=context.body_width,
        inline_preface=not is_dc and chapter_index > 0,
        include_chapter_heading=not is_dc,
    )


def _include_group(*, group: Sequence[FlowItem]) -> bool:
    """Return True when a group should be analyzed.

    Args:
        group: FlowItem group.
    Returns:
        True when the group is a verse or study paragraph.
    """

    first = group[0]
    return first.is_verse or first.style_name == "study"


def _line_text(*, html: str) -> str:
    """Return plain text for a line HTML fragment.

    Args:
        html: Line HTML fragment.
    Returns:
        Plain text string.
    """

    text = BeautifulSoup(html, "html.parser").get_text()
    text = text.replace("\xa0", " ").replace("\u00ad", "").replace("\u200a", "")
    return re.sub(r"\s+", " ", text).strip()


def _first_word(*, text: str) -> str:
    """Return the first word token for a line.

    Args:
        text: Plain text line.
    Returns:
        First word token, or empty string when absent.
    """

    match = FIRST_WORD_RE.search(text)
    return match.group(0) if match else ""


def _sup_prefix_letter(*, html: str) -> str:
    """Return superscript prefix letter when present at line start.

    Args:
        html: Line HTML fragment.
    Returns:
        Lowercased single-letter prefix, or empty string.
    """

    soup = BeautifulSoup(html, "html.parser")
    for node in soup.descendants:
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if not text:
                continue
            letter = text[0]
            if len(letter) == 1 and letter.isalpha():
                if any(
                    isinstance(parent, Tag) and parent.name == "sup"
                    for parent in node.parents
                ):
                    return letter.lower()
            return ""
        if isinstance(node, Tag) and node.name == "br":
            break
    return ""


def _strip_sup_prefix(*, word: str, prefix: str) -> str:
    """Return word with a superscript prefix removed when it matches.

    Args:
        word: Raw word token.
        prefix: Superscript prefix letter.
    Returns:
        Word without the prefix when applicable.
    """

    if prefix and word.lower().startswith(prefix) and len(word) > 1:
        return word[1:]
    return word


def _line_stretches(
    *,
    html: str,
    style: ParagraphStyle,
    width: float,
    hyphenator: Pyphen,
    location: SegmentLocation,
) -> list[StretchLine]:
    """Return stretch metrics for each line in a paragraph.

    Args:
        html: Paragraph HTML.
        style: Paragraph style.
        width: Wrap width in points.
        hyphenator: Hyphenation helper.
        location: SegmentLocation metadata.
    Returns:
        List of StretchLine entries.
    """

    para, line_htmls = _wrap_paragraph(
        html=html,
        style=style,
        hyphenator=hyphenator,
        width=width,
    )
    bl_para = getattr(para, "blPara", None)
    if bl_para is None:
        return []
    lines = list(getattr(bl_para, "lines", []))
    limit = min(len(lines), len(line_htmls))
    results: list[StretchLine] = []
    for idx in range(max(0, limit - 1)):
        line = lines[idx]
        word_count = int(getattr(line, "wordCount", 0) or 0)
        if word_count < 2:
            continue
        extra = float(getattr(line, "extraSpace", 0.0) or 0.0)
        if extra <= 0:
            continue
        next_html = line_htmls[idx + 1]
        next_word_raw = _first_word(text=_line_text(html=next_html))
        if not next_word_raw:
            continue
        sup_prefix = _sup_prefix_letter(html=next_html)
        next_word_clean = _strip_sup_prefix(
            word=next_word_raw,
            prefix=sup_prefix,
        )
        stretch = extra / max(word_count - 1, 1)
        results.append(
            StretchLine(
                location=location,
                line_index=idx + 1,
                line_count=limit,
                stretch_per_space=stretch,
                extra_space=extra,
                word_count=word_count,
                next_first_word_raw=next_word_raw,
                next_first_word_clean=next_word_clean,
                sup_prefix=sup_prefix,
            )
        )
    return results


def _iter_stretch_lines(
    *, corpus: Sequence[StandardWork], context: FontContext
) -> Iterable[StretchLine]:
    """Yield stretch metrics across the corpus.

    Args:
        corpus: Standard works to scan.
        context: Font context for wrapping.
    Returns:
        Iterable of StretchLine entries.
    """

    for _, book, chapter, chapter_index in _iter_chapters(corpus=corpus):
        items = _chapter_items(
            chapter=chapter,
            book=book,
            chapter_index=chapter_index,
            context=context,
        )
        for group in _group_lines(lines=items):
            if not _include_group(group=group):
                continue
            location = SegmentLocation.from_item(item=group[0])
            width = context.body_width if group[0].full_width else context.column_width
            sources = _paragraph_sources_from_group(
                group=group,
                styles=context.styles,
                hyphenator=context.hyphenator,
            )
            for source in sources:
                para = source.paragraph
                if not isinstance(para, Paragraph):
                    continue
                yield from _line_stretches(
                    html=source.recombined_html,
                    style=para.style,
                    width=width,
                    hyphenator=context.hyphenator,
                    location=location,
                )


def _write_top_lines(
    *,
    lines: Sequence[StretchLine],
    output_path: Path,
) -> Path:
    """Write stretch lines to a TSV file.

    Args:
        lines: StretchLine entries to write.
        output_path: Destination path.
    Returns:
        Output path resolved.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "book",
        "chapter",
        "verse",
        "segment_type",
        "line_index",
        "line_count",
        "stretch_per_space",
        "extra_space",
        "word_count",
        "next_first_word_raw",
        "next_first_word_clean",
        "sup_prefix",
    ]
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for entry in lines:
            handle.write(entry.tsv_row() + "\n")
    return output_path.resolve()


def main() -> None:
    """Run the justification stretch scan."""

    args = _parse_args()
    assert args.metadata_path.exists(), "metadata-scriptures.json is required"
    corpus = build_corpus(
        raw_root=args.raw_root,
        metadata_path=args.metadata_path,
        max_chapters=args.max_chapters,
    )
    context = _setup_context()
    stretches = list(_iter_stretch_lines(corpus=corpus, context=context))
    stretches.sort(
        key=lambda entry: (entry.stretch_per_space, entry.extra_space),
        reverse=True,
    )
    top_lines = stretches[: args.limit]
    output_path = _write_top_lines(lines=top_lines, output_path=args.output_path)
    print(f"Wrote {len(top_lines)} lines to {output_path}")


if __name__ == "__main__":
    main()
