"""Data structures for PDF layout planning and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import List, Sequence

from reportlab.platypus import Flowable, Paragraph

from ..models import FootnoteEntry


@dataclass(slots=True)
class FlowItem:
    """A renderable unit in the two-column text area.

    Args:
        paragraph: Flowable to render for this line.
        height: Pre-measured height for the flowable.
        line_html: HTML fragment for the wrapped line.
        style_name: Style key used for rebuilding paragraphs later.
        first_line: Whether this line starts a paragraph/segment.
        standard_work: Standard work slug for provenance.
        book_slug: Book slug for provenance.
        book_name: Human-readable book name.
        chapter: Chapter identifier.
        chapter_title: Chapter title from metadata.
        verse: Verse number or paragraph key.
        footnotes: Footnotes introduced on this line.
    """

    paragraph: Flowable
    height: float
    line_html: str
    style_name: str
    first_line: bool
    standard_work: str
    book_slug: str
    book_name: str
    chapter: str
    chapter_title: str
    verse: str | None
    footnotes: List[FootnoteEntry]
    segment_index: int = 0
    verse_line_index: int = 0
    verse_line_count: int = 1
    full_width: bool = False

    @property
    def is_verse(self) -> bool:
        """Return True when the item belongs to a verse line.

        Returns:
            True when ``verse`` looks like a verse identifier (digits with
            optional trailing letter).
        """

        if not self.verse:
            return False
        return bool(re.match(r"^\d+[a-z]?$", self.verse))


@dataclass(slots=True)
class FootnoteRow:
    """Footnote row cells ready for a ReportLab table.

    Args:
        chapter: Chapter cell (Paragraph or empty string).
        verse: Verse cell value.
        letter: Letter cell (Paragraph or empty string).
        text: Footnote paragraph cell.
    """

    chapter: Paragraph | str
    verse: str
    letter: Paragraph | str
    text: Paragraph

    def cells(self, *, include_chapter: bool) -> list[object]:
        """Return row cells for a table, optionally omitting chapter.

        Args:
            include_chapter: Whether to include the chapter column.
        Returns:
            List of cell objects for Table input.
        """

        if include_chapter:
            return [self.chapter, self.verse, self.letter, self.text]
        return [self.verse, self.letter, self.text]


@dataclass(slots=True)
class PageSlice:
    """Aggregated content for a single rendered page.

    Args:
        seen_chapters_in: Snapshot of (book_slug, chapter) pairs already seen before
            this page was laid out; used to keep footnote column decisions stable.
    """

    text_items: Sequence[FlowItem]
    text_blocks: List["TextBlock"]
    text_height: float
    header_height: float
    footnote_entries: List[FootnoteEntry]
    footnote_rows: List[FootnoteRow]
    footnote_row_heights: List[float]
    footnote_row_lines: List[int]
    header_flowables: List[Paragraph]
    range_label: str
    template_id: str
    footnote_height: float
    seen_chapters_in: set[tuple[str, str]]


@dataclass(slots=True)
class ChapterFlow:
    """Prepared flowables for a chapter."""

    header: List[Paragraph]
    items: List[FlowItem]
    force_new_page: bool


@dataclass(slots=True)
class FitResult:
    """Combined text and footnote fit for a candidate page."""

    count: int
    blocks: List["TextBlock"]
    text_height: float
    footnotes: List[FootnoteEntry]
    footnote_rows: List[FootnoteRow]
    footnote_heights: List[float]
    footnote_lines: List[int]
    footnote_height: float
    seen_chapters: set[tuple[str, str]]
    fits: bool


@dataclass(slots=True)
class PagePlan:
    """Finalized layout choices for a single page."""

    count: int
    blocks: List["TextBlock"]
    text_height: float
    header_height: float
    placed_notes: List[FootnoteEntry]
    footnote_rows: List[FootnoteRow]
    footnote_heights: List[float]
    footnote_lines: List[int]
    footnote_height: float
    pending_notes: List[FootnoteEntry]
    seen_chapters: set[tuple[str, str]]


@dataclass(slots=True)
class TextColumns:
    """Paragraphs split into left/right columns with shared height."""

    left: List[Flowable]
    right: List[Flowable]
    height: float


@dataclass(slots=True)
class TextBlock:
    """Block of text content on a page, either columns or full-width.

    Args:
        kind: "columns" or "full_width".
        columns: Two-column layout when kind=="columns".
        flowables: Full-width flowables when kind=="full_width".
        height: Measured block height.
        items: FlowItems represented by the block.
    """

    kind: str
    columns: TextColumns | None
    flowables: List[Flowable]
    height: float
    items: List[FlowItem]


@dataclass(slots=True)
class VerseRange:
    """Range of verses for page labeling.

    Args:
        book_name: Book name or abbreviation.
        start_chapter: Starting chapter identifier.
        start_verse: Starting verse identifier.
        end_chapter: Ending chapter identifier.
        end_verse: Ending verse identifier.
    """

    book_name: str
    start_chapter: str
    start_verse: str
    end_chapter: str
    end_verse: str

    def label(self) -> str:
        """Return the formatted label for the verse range.

        Returns:
            Label string for page headers.
        """

        if self.start_chapter == self.end_chapter:
            return (
                f"{self.book_name} {self.start_chapter}:{self.start_verse}\u2013{self.end_verse}"
            )
        return (
            f"{self.book_name} {self.start_chapter}:{self.start_verse}\u2013"
            f"{self.end_chapter}:{self.end_verse}"
        )
