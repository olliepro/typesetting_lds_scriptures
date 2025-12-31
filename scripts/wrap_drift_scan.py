"""
Scan for paragraph wrap drift after recombining line fragments.
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from bs4 import BeautifulSoup
from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scriptures.ingest import build_corpus
from scriptures.models import Book, Chapter, StandardWork
from scriptures.pdf.pdf_settings import PageSettings, build_styles, register_palatino
from scriptures.pdf.pdf_text import _line_fragments, _line_items_for_chapter
from scriptures.pdf.pdf_text_html import _paragraph_from_html
from scriptures.pdf.pdf_text_line_helpers import (
    ParagraphSource,
    _group_lines,
    _paragraph_sources_from_group,
)
from scriptures.pdf.pdf_types import FlowItem

_FIRST_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


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
class SegmentLocation:
    """Identifying metadata for a paragraph/verse segment.

    Args:
        standard_work: Standard work slug.
        book_slug: Book slug.
        chapter: Chapter identifier.
        verse: Verse identifier, if present.
    """

    standard_work: str
    book_slug: str
    chapter: str
    verse: str | None

    @classmethod
    def from_item(cls, *, item: FlowItem) -> "SegmentLocation":
        """Create a location from a FlowItem.

        Args:
            item: FlowItem containing provenance metadata.
        Returns:
            SegmentLocation instance.
        """

        return cls(
            standard_work=item.standard_work,
            book_slug=item.book_slug,
            chapter=item.chapter,
            verse=item.verse,
        )

    def label(self) -> str:
        """Return a display label for logs.

        Returns:
            Label string for the segment location.
        """

        if self.verse:
            return f"{self.standard_work}/{self.book_slug} {self.chapter}:{self.verse}"
        return f"{self.standard_work}/{self.book_slug} {self.chapter}"


@dataclass(slots=True)
class WrapDiff:
    """Differences between original and recombined wraps.

    Args:
        location: Segment location metadata.
        style_name: Style name used in PDF layout.
        full_width: Whether the segment spans full width.
        width: Wrap width in points.
        original_lines: Original wrapped line HTML.
        final_lines: Lines after recombining and rewrapping.
        rehyphenated_lines: Lines after rehyphenating and rewrapping.
        final_mismatches: Count of mismatched line positions in final_lines.
        rehyphenated_mismatches: Count of mismatched line positions after rehyphenation.
    """

    location: SegmentLocation
    style_name: str
    full_width: bool
    width: float
    original_lines: list[str]
    final_lines: list[str]
    rehyphenated_lines: list[str]
    final_mismatches: int
    rehyphenated_mismatches: int

    def drifted(self) -> bool:
        """Return True when recombined wrapping differs from the original.

        Returns:
            True when final mismatches are non-zero.
        """

        return self.final_mismatches > 0

    def improved(self) -> bool:
        """Return True when rehyphenation reduces mismatches.

        Returns:
            True when rehyphenation yields fewer mismatches.
        """

        return self.rehyphenated_mismatches < self.final_mismatches

    def rehyphenation_changes_without_drift(self) -> bool:
        """Return True when rehyphenation changes a stable wrap.

        Returns:
            True when final lines match original but rehyphenation differs.
        """

        return self.final_mismatches == 0 and self.rehyphenated_mismatches > 0

    def warning_message(self, *, label: str = "Wrap drift detected") -> str:
        """Return the warning message payload.

        Args:
            label: Heading prefix for the warning message.
        Returns:
            Warning string with wrap comparisons.
        """

        header = (
            f"{label}"
            f" | {self.location.label()}"
            f" | style={self.style_name}"
            f" | width={self.width:.2f}"
            f" | full_width={self.full_width}"
            f" | mismatches={self.final_mismatches}"
            f" | rehyphenated={self.rehyphenated_mismatches}"
        )
        blocks = [
            header,
            self._format_lines(label="original", lines=self.original_lines),
            self._format_lines(label="final", lines=self.final_lines),
            self._format_lines(label="rehyphenated", lines=self.rehyphenated_lines),
        ]
        return "\n".join(blocks)

    def _format_lines(self, *, label: str, lines: Sequence[str]) -> str:
        """Return a formatted block for a line list.

        Args:
            label: Section label.
            lines: Sequence of HTML strings.
        Returns:
            Formatted multi-line string.
        """

        header = f"{label} ({len(lines)} lines):"
        items = [f"  {idx + 1:02d}: {line}" for idx, line in enumerate(lines)]
        return "\n".join([header, *items])


@dataclass(slots=True)
class ScanStats:
    """Running statistics for wrap drift scanning.

    Args:
        total_segments: Number of segments checked.
        drift_segments: Number of segments with wrap drift.
        improved_segments: Number of segments improved by rehyphenation.
        rehyphenation_no_drift_changes: No-drift segments changed by rehyphenation.
        warnings_emitted: Total warnings emitted.
    """

    total_segments: int = 0
    drift_segments: int = 0
    improved_segments: int = 0
    rehyphenation_no_drift_changes: int = 0
    warnings_emitted: int = 0


def _parse_args() -> argparse.Namespace:
    """Return CLI arguments for the wrap drift scanner.

    Returns:
        argparse.Namespace of parsed CLI args.
    """

    parser = argparse.ArgumentParser(
        description="Warn when recombined wraps differ from original line wraps."
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw"),
        help="Directory containing scraped JSON data.",
    )
    parser.add_argument(
        "--metadata-path",
        type=Path,
        default=Path("data/raw/metadata-scriptures.json"),
        help="Path to metadata-scriptures.json.",
    )
    parser.add_argument(
        "--max-chapters",
        type=int,
        default=None,
        help="Optional cap on chapters per book.",
    )
    parser.add_argument(
        "--max-warnings",
        type=int,
        default=None,
        help="Stop after emitting this many warnings.",
    )
    return parser.parse_args()


def _setup_context() -> FontContext:
    """Return prepared font/style context for wrap scanning.

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
        True when the group is not suitable for wrap diffing.
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


def _paragraph_lines_normalized(
    *, paragraph: Paragraph, width: float
) -> tuple[list[str], list[str]]:
    """Return wrapped lines for a paragraph with normalized text.

    Args:
        paragraph: Paragraph to wrap.
        width: Wrap width in points.
    Returns:
        Tuple of (lines, normalized_lines).
    """

    lines = _line_fragments(para=paragraph, width=width)
    return lines, _normalize_lines(lines=lines)


def _rehyphenated_lines_normalized(
    *,
    html: str,
    style: ParagraphStyle,
    width: float,
    hyphenator: Pyphen,
) -> tuple[list[str], list[str]]:
    """Return rehyphenated wrapped lines with normalized text.

    Args:
        html: HTML fragment to rehyphenate.
        style: Paragraph style for wrapping.
        width: Wrap width in points.
        hyphenator: Hyphenation helper.
    Returns:
        Tuple of (lines, normalized_lines).
    """

    paragraph = _paragraph_from_html(
        html=html,
        style=style,
        hyphenator=hyphenator,
        insert_hair_space=True,
    )
    lines = _line_fragments(para=paragraph, width=width)
    return lines, _normalize_lines(lines=lines)


def _normalize_line_text(*, line_html: str) -> str:
    """Return normalized plain text for comparison.

    Args:
        line_html: HTML line to normalize.
    Returns:
        Normalized plain text string.
    """

    text = BeautifulSoup(line_html, "html.parser").get_text()
    text = text.replace("\xa0", " ").replace("\u00ad", "").replace("\u200a", "")
    return re.sub(r"\s+", " ", text).strip()


def _first_word(*, line_text: str) -> str:
    """Return the first word token for a normalized line.

    Args:
        line_text: Normalized plain text line.
    Returns:
        Lowercased first word token, or empty string when absent.
    """

    match = _FIRST_WORD_RE.search(line_text)
    if not match:
        return ""
    return match.group(0).lower()


def _normalize_lines(*, lines: Sequence[str]) -> list[str]:
    """Return normalized line text for a list of HTML lines.

    Args:
        lines: HTML line strings.
    Returns:
        Normalized plain text line list.
    """

    return [_normalize_line_text(line_html=line) for line in lines]


def _source_line_sets(*, source: ParagraphSource) -> tuple[list[str], list[str]]:
    """Return original and normalized lines for a source.

    Args:
        source: ParagraphSource to inspect.
    Returns:
        Tuple of (original_lines, normalized_lines).
    """

    original_lines = list(source.line_htmls)
    return original_lines, _normalize_lines(lines=original_lines)


def _line_mismatch_count(*, first: Sequence[str], second: Sequence[str]) -> int:
    """Return the count of mismatched line positions by first word.

    Args:
        first: First normalized line list.
        second: Second normalized line list.
    Returns:
        Count of mismatched first-word line positions and length differences.
    """

    count = abs(len(first) - len(second))
    limit = min(len(first), len(second))
    for idx in range(limit):
        left = _first_word(line_text=first[idx])
        right = _first_word(line_text=second[idx])
        if left != right:
            count += 1
    return count


def _compare_source(
    *,
    source: ParagraphSource,
    location: SegmentLocation,
    width: float,
    full_width: bool,
    hyphenator: Pyphen,
) -> WrapDiff:
    """Compare original vs recombined wraps for a paragraph source.

    Args:
        source: ParagraphSource with recombined paragraph and HTML.
        location: Segment location metadata.
        width: Wrap width in points.
        full_width: Whether the segment spans full width.
        hyphenator: Hyphenator for rehyphenated comparison.
    Returns:
        WrapDiff describing original, final, and rehyphenated wraps.
    """

    original_lines, original_norm = _source_line_sets(source=source)
    paragraph = source.paragraph
    assert isinstance(paragraph, Paragraph), "Expected Paragraph flowable."
    final_lines, final_norm = _paragraph_lines_normalized(
        paragraph=paragraph,
        width=width,
    )
    rehyphenated_lines, rehyphenated_norm = _rehyphenated_lines_normalized(
        html=source.recombined_html,
        style=paragraph.style,
        width=width,
        hyphenator=hyphenator,
    )
    return _build_diff(
        segment_location=location,
        style_name=source.style_name,
        width=width,
        full_width=full_width,
        original_lines=original_lines,
        final_lines=final_lines,
        rehyphenated_lines=rehyphenated_lines,
        final_mismatches=_line_mismatch_count(
            first=original_norm, second=final_norm
        ),
        rehyphenated_mismatches=_line_mismatch_count(
            first=original_norm, second=rehyphenated_norm
        ),
    )


def _build_diff(
    *,
    segment_location: SegmentLocation,
    style_name: str,
    width: float,
    full_width: bool,
    original_lines: Sequence[str],
    final_lines: Sequence[str],
    rehyphenated_lines: Sequence[str],
    final_mismatches: int,
    rehyphenated_mismatches: int,
) -> WrapDiff:
    """Return a WrapDiff for a segment comparison.

    Args:
        segment_location: Segment location metadata.
        style_name: Style name or key for the segment.
        width: Wrap width in points.
        full_width: Whether the segment spans full width.
        original_lines: Original wrapped lines.
        final_lines: Rewrapped lines without hyphenation.
        rehyphenated_lines: Rewrapped lines with rehyphenation.
    Returns:
        WrapDiff instance.
    """

    return WrapDiff(
        location=segment_location,
        style_name=style_name,
        full_width=full_width,
        width=width,
        original_lines=list(original_lines),
        final_lines=list(final_lines),
        rehyphenated_lines=list(rehyphenated_lines),
        final_mismatches=final_mismatches,
        rehyphenated_mismatches=rehyphenated_mismatches,
    )


def _scan_chapter(
    *,
    chapter: Chapter,
    book: Book,
    chapter_index: int,
    context: FontContext,
    stats: ScanStats,
    max_warnings: int | None,
) -> bool:
    """Scan a chapter and update stats.

    Args:
        chapter: Chapter to scan.
        book: Book containing the chapter.
        chapter_index: Index of the chapter within the book.
        context: Font context for wrapping.
        stats: Mutable ScanStats accumulator.
        max_warnings: Optional max warnings to emit.
    Returns:
        True when scanning should stop early.
    """

    items = _chapter_items(
        chapter=chapter,
        book=book,
        chapter_index=chapter_index,
        context=context,
    )
    for group in _group_lines(lines=items):
        if _should_skip_group(group=group):
            continue
        width = context.body_width if group[0].full_width else context.column_width
        location = SegmentLocation.from_item(item=group[0])
        sources = _paragraph_sources_from_group(
            group=group,
            styles=context.styles,
            hyphenator=context.hyphenator,
        )
        for source in sources:
            if not isinstance(source.paragraph, Paragraph):
                continue
            diff = _compare_source(
                source=source,
                location=location,
                width=width,
                full_width=group[0].full_width,
                hyphenator=context.hyphenator,
            )
            _update_stats_for_diff(stats=stats, diff=diff)
            if _warn_for_diff(diff=diff, stats=stats, max_warnings=max_warnings):
                return True
    return False


def _update_stats_for_diff(*, stats: ScanStats, diff: WrapDiff) -> None:
    """Update scan statistics from a wrap diff.

    Args:
        stats: ScanStats accumulator.
        diff: WrapDiff to summarize.
    Returns:
        None.
    """

    stats.total_segments += 1
    if diff.drifted():
        stats.drift_segments += 1
        if diff.improved():
            stats.improved_segments += 1
    if diff.rehyphenation_changes_without_drift():
        stats.rehyphenation_no_drift_changes += 1


def _warn_for_diff(
    *, diff: WrapDiff, stats: ScanStats, max_warnings: int | None
) -> bool:
    """Warn for a wrap drift and return True when max warnings reached.

    Args:
        diff: WrapDiff to warn about.
        stats: ScanStats accumulator.
        max_warnings: Optional max warnings to emit.
    Returns:
        True when max warnings reached.
    """

    if not diff.drifted():
        return False
    label = _warning_label()
    warnings.warn(diff.warning_message(label=label), stacklevel=2)
    stats.warnings_emitted += 1
    return bool(max_warnings and stats.warnings_emitted >= max_warnings)


def _warning_label() -> str:
    """Return the warning label for a wrap diff.

    Returns:
        Warning label string.
    """

    return "Wrap drift detected"


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


def scan_corpus(
    *,
    corpus: Sequence[StandardWork],
    context: FontContext,
    max_warnings: int | None,
) -> ScanStats:
    """Scan a corpus and emit warnings when wrap drift is detected.

    Args:
        corpus: Standard works to scan.
        context: Font context for wrapping.
        max_warnings: Optional cap on warnings emitted.
    Returns:
        ScanStats with drift and improvement counts.

    Example:
        >>> scan_corpus(corpus=[], context=_setup_context(), max_warnings=None)
        ScanStats(total_segments=0, drift_segments=0, improved_segments=0, rehyphenation_no_drift_changes=0, warnings_emitted=0)
    """

    stats = ScanStats()
    for _, book, chapter, chapter_index in _iter_chapters(corpus=corpus):
        should_stop = _scan_chapter(
            chapter=chapter,
            book=book,
            chapter_index=chapter_index,
            context=context,
            stats=stats,
            max_warnings=max_warnings,
        )
        if should_stop:
            break
    return stats


def _summary_text(*, stats: ScanStats) -> str:
    """Return a summary string for scan stats.

    Args:
        stats: ScanStats to summarize.
    Returns:
        Summary string.
    """

    return (
        "Wrap drift scan complete\n"
        f"Segments checked: {stats.total_segments}\n"
        f"Wrap drift segments: {stats.drift_segments}\n"
        f"Rehyphenation improvements: {stats.improved_segments}\n"
        f"Rehyphenation changes without drift: {stats.rehyphenation_no_drift_changes}\n"
        f"Warnings emitted: {stats.warnings_emitted}"
    )


def main() -> None:
    """Run the wrap drift scanner across the corpus.

    Example:
        >>> main()  # doctest: +SKIP
    """

    args = _parse_args()
    assert args.metadata_path.exists(), "metadata-scriptures.json is required"
    warnings.simplefilter("always", UserWarning)
    corpus = build_corpus(
        raw_root=args.raw_root,
        metadata_path=args.metadata_path,
        max_chapters=args.max_chapters,
    )
    context = _setup_context()
    stats = scan_corpus(
        corpus=corpus,
        context=context,
        max_warnings=args.max_warnings,
    )
    print(_summary_text(stats=stats))


if __name__ == "__main__":
    main()
