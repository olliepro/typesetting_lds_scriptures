"""Extract words hyphenated across line wraps."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from bs4 import BeautifulSoup
from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scriptures.ingest import build_corpus
from scriptures.models import Book, Chapter, StandardWork
from scriptures.pdf.pdf_settings import PageSettings, build_styles, register_palatino
from scriptures.pdf.pdf_text import _line_items_for_chapter
from scriptures.pdf.pdf_text_line_helpers import _group_lines
from scriptures.pdf.pdf_types import FlowItem

HYPHEN_CHARS = ("-", "\u00ad", "\u2010", "\u2011")
_TRAILING_WORD_RE = re.compile(r"([A-Za-z0-9]+(?:'[A-Za-z0-9]+)?)$")
_LEADING_WORD_RE = re.compile(r"([A-Za-z0-9]+(?:'[A-Za-z0-9]+)?)")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class FontContext:
    """Prepared font, style, and width settings for wrap scanning.

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
class HyphenSplit:
    """Hyphenated word split across two wrapped lines.

    Args:
        standard_work: Standard work slug.
        book_slug: Book slug.
        chapter: Chapter identifier.
        verse: Verse identifier, if present.
        segment_index: Segment index within the verse.
        line_index: 1-based index within the group.
        line_count: Total lines in the group.
        prefix: Word fragment before the hyphen.
        suffix: Word fragment after the hyphen.
        full_word: Reconstructed word without the hyphen.
        line_text: Plain text of the hyphenated line.
        next_line_text: Plain text of the following line.
    """

    standard_work: str
    book_slug: str
    chapter: str
    verse: str | None
    segment_index: int
    line_index: int
    line_count: int
    prefix: str
    suffix: str
    full_word: str
    line_text: str
    next_line_text: str

    def tsv_row(self) -> str:
        """Return a TSV row for the split.

        Returns:
            Tab-separated string with location and split details.

        Example:
            >>> split = HyphenSplit(
            ...     standard_work="book-of-mormon",
            ...     book_slug="1-nephi",
            ...     chapter="1",
            ...     verse="1",
            ...     segment_index=0,
            ...     line_index=1,
            ...     line_count=5,
            ...     prefix="pro",
            ...     suffix="phet",
            ...     full_word="prophet",
            ...     line_text="pro-",
            ...     next_line_text="phet",
            ... )
            >>> "prophet" in split.tsv_row()
            True
        """

        values = [
            self.standard_work,
            self.book_slug,
            self.chapter,
            self.verse or "",
            str(self.segment_index),
            str(self.line_index),
            str(self.line_count),
            self.prefix,
            self.suffix,
            self.full_word,
            self.line_text,
            self.next_line_text,
        ]
        cleaned = [_tsv_safe(value=value) for value in values]
        return "\t".join(cleaned)


def _tsv_safe(*, value: str) -> str:
    """Return a TSV-safe string.

    Args:
        value: Raw string value.
    Returns:
        Value with tabs/newlines replaced by spaces.
    """

    return value.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _parse_args() -> argparse.Namespace:
    """Return CLI arguments for the hyphen split extractor.

    Returns:
        argparse.Namespace of parsed CLI args.
    """

    parser = argparse.ArgumentParser(
        description="Extract words hyphenated across wrapped line breaks."
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
        "--output-path",
        type=Path,
        default=Path("output/line_split_hyphens.tsv"),
        help="Output TSV path.",
    )
    parser.add_argument(
        "--max-chapters",
        type=int,
        default=None,
        help="Optional cap on chapters per book.",
    )
    return parser.parse_args()


def _setup_context() -> FontContext:
    """Return prepared font/style context for extraction.

    Returns:
        FontContext containing styles, hyphenator, and widths.

    Example:
        >>> ctx = _setup_context()
        >>> ctx.column_width > 0
        True
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


def _should_skip_group(*, group: Sequence[FlowItem]) -> bool:
    """Return True when a group should be skipped.

    Args:
        group: FlowItem group.
    Returns:
        True when the group is not suitable for extraction.
    """

    first_style = group[0].style_name
    if first_style in {
        "spacer",
        "chapter_heading_group",
        "section_heading_group",
        "book_title_group",
    }:
        return True
    return all(not item.line_html.strip() for item in group)


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


def _line_text(*, line_html: str) -> str:
    """Return plain text for a line HTML fragment.

    Args:
        line_html: HTML fragment for a wrapped line.
    Returns:
        Plain text with collapsed whitespace.
    """

    soup = BeautifulSoup(line_html, "html.parser")
    for sup in list(soup.find_all("sup")):
        sup.decompose()
    text = soup.get_text()
    text = text.replace("\xa0", " ").replace("\u200a", "")
    return _WHITESPACE_RE.sub(" ", text).strip()


def _ends_with_split_hyphen(*, line_text: str) -> bool:
    """Return True when a line ends with a hyphen used for a split.

    Args:
        line_text: Plain text line.
    Returns:
        True when the line ends with a hyphen-like character.
    """

    return bool(line_text) and line_text[-1] in HYPHEN_CHARS


def _split_word_parts(*, line_text: str, next_line_text: str) -> tuple[str, str]:
    """Return the split word fragments from two lines.

    Args:
        line_text: Line text ending with a hyphen.
        next_line_text: Following line text.
    Returns:
        Tuple of (prefix, suffix) fragments, empty when not found.
    """

    if not _ends_with_split_hyphen(line_text=line_text):
        return "", ""
    base = line_text[:-1]
    prefix_match = _TRAILING_WORD_RE.search(base)
    suffix_match = _LEADING_WORD_RE.search(next_line_text)
    if not prefix_match or not suffix_match:
        return "", ""
    return prefix_match.group(1), suffix_match.group(1)


def _iter_hyphen_splits(
    *, corpus: Sequence[StandardWork], context: FontContext
) -> Iterable[HyphenSplit]:
    """Yield hyphenated line-split words from the corpus.

    Args:
        corpus: Standard works to scan.
        context: Font context for wrapping.
    Returns:
        Iterable of HyphenSplit entries.

    Example:
        >>> list(_iter_hyphen_splits(corpus=[], context=_setup_context()))
        []
    """

    for _, book, chapter, chapter_index in _iter_chapters(corpus=corpus):
        items = _chapter_items(
            chapter=chapter,
            book=book,
            chapter_index=chapter_index,
            context=context,
        )
        for group in _group_lines(lines=items):
            if _should_skip_group(group=group):
                continue
            line_texts = [_line_text(line_html=item.line_html) for item in group]
            for idx in range(len(line_texts) - 1):
                left = line_texts[idx]
                right = line_texts[idx + 1]
                prefix, suffix = _split_word_parts(
                    line_text=left,
                    next_line_text=right,
                )
                if not prefix or not suffix:
                    continue
                item = group[idx]
                yield HyphenSplit(
                    standard_work=item.standard_work,
                    book_slug=item.book_slug,
                    chapter=item.chapter,
                    verse=item.verse,
                    segment_index=item.segment_index,
                    line_index=idx + 1,
                    line_count=len(group),
                    prefix=prefix,
                    suffix=suffix,
                    full_word=f"{prefix}{suffix}",
                    line_text=left,
                    next_line_text=right,
                )


def _write_splits(
    *, splits: Iterable[HyphenSplit], output_path: Path
) -> tuple[int, Path]:
    """Write hyphen splits to a TSV file.

    Args:
        splits: Iterable of HyphenSplit entries.
        output_path: Path to write the TSV file.
    Returns:
        Tuple of (count_written, resolved_path).
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "standard_work",
        "book_slug",
        "chapter",
        "verse",
        "segment_index",
        "line_index",
        "line_count",
        "prefix",
        "suffix",
        "full_word",
        "line_text",
        "next_line_text",
    ]
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for split in splits:
            handle.write(split.tsv_row() + "\n")
            count += 1
    return count, output_path.resolve()


def main() -> None:
    """Run the hyphenated line-split extractor.

    Example:
        >>> main()  # doctest: +SKIP
    """

    args = _parse_args()
    assert args.metadata_path.exists(), "metadata-scriptures.json is required"
    corpus = build_corpus(
        raw_root=args.raw_root,
        metadata_path=args.metadata_path,
        max_chapters=args.max_chapters,
    )
    context = _setup_context()
    count, output_path = _write_splits(
        splits=_iter_hyphen_splits(corpus=corpus, context=context),
        output_path=args.output_path,
    )
    print(f"Wrote {count} hyphenated splits to {output_path}")


if __name__ == "__main__":
    main()
