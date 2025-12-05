"""
PDF generation for the scraped scripture corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
import re
import os
import time
from math import isclose
import html as htmllib

from bs4 import BeautifulSoup
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    ListFlowable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
)
from reportlab.platypus.tables import TableStyle
from reportlab.platypus.flowables import Flowable

from pyphen import Pyphen

from .layout_utils import measure_height, optimal_partition
from .models import Book, Chapter, FootnoteEntry, StandardWork, Verse
from .text import hyphenate_html
from .cleaning import clean_text

HAIR_SPACE = "\u200a"
DASH_CHARS = ("-", "\u2013", "\u2014")


@dataclass(slots=True)
class FlowItem:
    """A renderable unit in the two-column text area."""

    paragraph: Paragraph
    height: float
    line_html: str
    style_name: str
    first_line: bool
    standard_work: str
    book_slug: str
    book_name: str
    chapter: str
    verse: str | None
    footnotes: List[FootnoteEntry]
    segment_index: int = 0
    verse_line_index: int = 0
    verse_line_count: int = 1

    @property
    def is_verse(self) -> bool:
        return self.verse is not None


class StackedFlowable(Flowable):
    """Stack child flowables vertically as a single unbreakable block."""

    def __init__(self, content: Sequence[Flowable], logical_lines: int = 1):
        super().__init__()
        self.content = list(content)
        self.width = 0.0
        self.height = 0.0
        self.logical_lines = max(1, logical_lines)

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self.width = avail_width
        heights = []
        for child in self.content:
            _, h = child.wrap(avail_width, avail_height)
            heights.append(h)
        self.height = sum(heights)
        return avail_width, self.height

    def draw(self) -> None:
        y = self.height
        for child in self.content:
            _, h = child.wrap(self.width, self.height)
            y -= h
            child.drawOn(self.canv, 0, y)


@dataclass(slots=True)
class PageSlice:
    """Aggregated content for a single rendered page.

    Attributes:
        seen_chapters_in: Snapshot of chapters already seen before this page was laid
            out; used to keep footnote column decisions stable during refresh.
    """

    text_items: List[FlowItem]
    text_columns: "TextColumns"
    text_height: float
    header_height: float
    footnote_entries: List[FootnoteEntry]
    footnote_rows: List[tuple[str, str, str, Paragraph]]
    footnote_row_heights: List[float]
    footnote_row_lines: List[int]
    header_flowables: List[Paragraph]
    range_label: str
    template_id: str
    footnote_height: float
    seen_chapters_in: set[str]


@dataclass(slots=True)
class ChapterFlow:
    """Prepared flowables for a chapter."""

    header: List[Paragraph]
    items: List[FlowItem]
    force_new_page: bool


@dataclass(slots=True)
class LayoutCache:
    """Memoize expensive text column layouts for reuse during paging."""

    items: Sequence[FlowItem]
    settings: "PageSettings"
    styles: Dict[str, ParagraphStyle]
    _text_cache: Dict[tuple[int, int], tuple["TextColumns", float]] = field(
        default_factory=dict
    )

    def columns_for(self, start_idx: int, count: int) -> tuple["TextColumns", float]:
        """Return column layout and height for a contiguous slice of FlowItems."""

        key = (start_idx, count)
        if key in self._text_cache:
            return self._text_cache[key]
        columns, height = _layout_columns_unfitted(
            self.items[start_idx : start_idx + count], self.settings, self.styles
        )
        self._text_cache[key] = (columns, height)
        return columns, height


def _text_height_with_padding(
    height: float, has_footnotes: bool, settings: "PageSettings"
) -> float:
    """Add bottom padding that is applied when footnotes are present."""

    return height + (settings.column_gap / 2 if has_footnotes else 0.0)


@dataclass(slots=True)
class FitResult:
    """Combined text and footnote fit for a candidate page."""

    count: int
    columns: "TextColumns"
    text_height: float
    footnotes: List[FootnoteEntry]
    footnote_rows: List[tuple[str, str, str, Paragraph]]
    footnote_heights: List[float]
    footnote_lines: List[int]
    footnote_height: float
    seen_chapters: set[str]
    fits: bool


@dataclass(slots=True)
class PagePlan:
    """Finalized layout choices for a single page."""

    count: int
    columns: "TextColumns"
    text_height: float
    header_height: float
    placed_notes: List[FootnoteEntry]
    footnote_rows: List[tuple[str, str, str, Paragraph]]
    footnote_heights: List[float]
    footnote_lines: List[int]
    footnote_height: float
    pending_notes: List[FootnoteEntry]
    seen_chapters: set[str]


def _chapter_flows(
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
) -> List[ChapterFlow]:
    """Prepare ChapterFlow objects for a book."""

    flows: List[ChapterFlow] = []
    inner_column_width = settings.text_column_width() - settings.column_gap / 2
    for idx, chapter in enumerate(book.chapters):
        is_dc = book.standard_work == "doctrine-and-covenants"
        header = _full_width_header(chapter, styles, hyphenator) if is_dc else []
        inline_preface = not is_dc and idx > 0
        items = _line_items_for_chapter(
            chapter=chapter,
            book=book,
            styles=styles,
            hyphenator=hyphenator,
            column_width=inner_column_width,
            inline_preface=inline_preface,
            include_chapter_heading=not is_dc,
        )
        flows.append(
            ChapterFlow(
                header=header,
                items=items,
                force_new_page=is_dc or idx == 0,
            )
        )
    return flows


def _collect_items(
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
) -> tuple[List[FlowItem], Dict[int, List[Paragraph]], List[int]]:
    """Flatten chapter flows and track headers/breaks."""

    flows = _chapter_flows(book, styles, hyphenator, settings)
    all_items: List[FlowItem] = []
    header_map: Dict[int, List[Paragraph]] = {}
    breakpoints: List[int] = []
    for flow in flows:
        start_idx = len(all_items)
        if flow.force_new_page:
            breakpoints.append(start_idx)
            if flow.header:
                header_map[start_idx] = flow.header
        elif flow.header:
            header_map[start_idx] = flow.header
        all_items.extend(flow.items)
    return all_items, header_map, breakpoints


def _available_text_height(header_height: float, settings: PageSettings) -> float:
    """Return vertical space available for body text on the page."""

    return max(0.0, settings.body_height - header_height - settings.text_extra_buffer)


def _expected_line_count(
    items: Sequence[FlowItem],
    start_idx: int,
    stop_idx: int,
    available_text: float,
) -> int:
    """Estimate a starting line count using average measured line height.

    The estimate intentionally over-allocates a bit to reduce upward search work.
    """

    slice_items = items[start_idx:stop_idx]
    if not slice_items:
        return 1
    avg_height = sum(itm.height for itm in slice_items) / len(slice_items)
    if avg_height <= 0:
        return 1
    estimate = int((available_text / avg_height) * 2.2)
    return max(1, min(stop_idx - start_idx, estimate))


class PageFitter:
    """Search for the max text/footnote combo, then fill remaining text space."""

    def __init__(
        self,
        items: Sequence[FlowItem],
        start_idx: int,
        stop_idx: int,
        header_height: float,
        settings: PageSettings,
        styles: Dict[str, ParagraphStyle],
        hyphenator: Pyphen,
        pending_notes: Sequence[FootnoteEntry],
        seen_chapters: set[str],
    ) -> None:
        """Create a fitter for a contiguous run of FlowItems on one page."""
        self.items = items
        self.start_idx = start_idx
        self.stop_idx = stop_idx
        self.header_height = header_height
        self.settings = settings
        self.styles = styles
        self.hyphenator = hyphenator
        self.pending_notes = list(pending_notes)
        self.seen_chapters = set(seen_chapters)
        self.cache = LayoutCache(items, settings, styles)
        self.available_text = _available_text_height(header_height, settings)
        self.max_count = stop_idx - start_idx

    def _measure_fit(self, count: int) -> FitResult:
        """Return combined text and footnote layout for ``count`` lines."""
        columns, text_height_raw = self.cache.columns_for(self.start_idx, count)
        new_notes = _footnotes_for_items(
            self.items[self.start_idx : self.start_idx + count]
        )
        rows, heights, lines, seen = _footnote_rows(
            self.pending_notes + new_notes,
            self.styles,
            self.hyphenator,
            self.settings,
            seen_chapters=self.seen_chapters,
        )
        fn_height = _footnote_height(heights, self.settings)
        text_height = _text_height_with_padding(
            text_height_raw, bool(rows), self.settings
        )
        available_fn = self.settings.body_height - self.header_height - text_height
        _debug(
            "[measure] count=%d text_raw=%.2f text_pad=%.2f "
            "avail_text=%.2f avail_fn=%.2f fn_h=%.2f rows=%d new_notes=%d pending=%d"
            % (
                count,
                text_height_raw,
                text_height,
                self.available_text,
                available_fn,
                fn_height,
                len(rows),
                len(new_notes),
                len(self.pending_notes),
            )
        )
        fits = text_height <= self.available_text + EPSILON and fn_height <= max(
            0.0, available_fn + EPSILON
        )
        return FitResult(
            count=count,
            columns=columns,
            text_height=text_height,
            footnotes=new_notes,
            footnote_rows=rows,
            footnote_heights=heights,
            footnote_lines=lines,
            footnote_height=fn_height,
            seen_chapters=seen,
            fits=fits,
        )

    def _balanced_fit(self) -> FitResult:
        """Find the largest line count where text and footnotes both fit."""
        start = _expected_line_count(
            self.items, self.start_idx, self.stop_idx, self.available_text
        )
        count = min(self.max_count, start)
        step = max(1, self.max_count // 6)
        best: FitResult | None = None
        last_outcome: bool | None = None
        iterations = 0
        max_iterations = 200

        if DEBUG_PAGINATION:
            _debug(
                f"[fit] start_idx={self.start_idx} stop_idx={self.stop_idx} "
                f"start_count={count} step={step} max_count={self.max_count} "
                f"avail_text={self.available_text:.1f}"
            )

        while iterations < max_iterations:
            iterations += 1
            fit = self._measure_fit(count)
            if fit.fits and (best is None or fit.count > best.count):
                best = fit

            outcome = fit.fits
            direction_up = outcome  # grow when fit, shrink when not

            # Detect flip to shrink step (anneal) only at the boundary.
            if last_outcome is not None and outcome != last_outcome:
                step = max(1, step // 2)
                # If we've reached unit step and seen both sides, stop at best.
                if step == 1 and best is not None:
                    if DEBUG_PAGINATION:
                        _debug(
                            f"[fit] boundary reached at count={count} best={best.count} "
                            f"text_h={best.text_height:.1f} fn_h={best.footnote_height:.1f}"
                        )
                    break

            last_outcome = outcome

            if direction_up:
                if count >= self.max_count or step == 0:
                    break
                next_count = min(self.max_count, count + step)
                if next_count == count:
                    break
                count = next_count
            else:
                if count == 1 or step == 0:
                    break
                next_count = max(1, count - step)
                if next_count == count:
                    break
                count = next_count

            # If step is 1 and we have best fit larger than current but current is non-fit, continue moving downward.
            if step == 1 and not outcome and count == 1:
                break

            if DEBUG_PAGINATION and iterations % 25 == 0:
                _debug(
                    f"[fit] iter={iterations} count={count} step={step} "
                    f"fits={fit.fits} text_h={fit.text_height:.1f} "
                    f"fn_h={fit.footnote_height:.1f}"
                )

        if best:
            if DEBUG_PAGINATION:
                _debug(
                    f"[fit] best={best.count} iters={iterations} "
                    f"text_h={best.text_height:.1f} fn_h={best.footnote_height:.1f}"
                )
            return best

        # Final safety: sweep downward to find the largest fitting count.
        for c in range(min(count, self.max_count), 0, -1):
            fit = self._measure_fit(c)
            if fit.fits:
                if DEBUG_PAGINATION:
                    _debug(
                        f"[fit] fallback found count={fit.count} "
                        f"text_h={fit.text_height:.1f} fn_h={fit.footnote_height:.1f}"
                    )
                return fit
        final_fit = self._measure_fit(1)
        if DEBUG_PAGINATION:
            _debug(
                f"[fit] fallback count=1 text_h={final_fit.text_height:.1f} "
                f"fn_h={final_fit.footnote_height:.1f}"
            )
        return final_fit

    def plan(self) -> PagePlan:
        """Compute the final PagePlan for the current page window.

        Example:
            fitter = PageFitter(items, 0, 40, header_h, settings, styles, hyph, [], set())
            plan = fitter.plan()
        """
        base = self._balanced_fit()

        # Place footnotes for the base fit (they must fit together with text).
        available_fn_base = max(
            0.0, self.settings.body_height - self.header_height - base.text_height
        )
        (
            placed_notes,
            pending_notes,
            fn_rows,
            fn_heights,
            fn_lines,
            fn_height,
            seen,
        ) = _place_footnotes(
            pending=self.pending_notes,
            new_entries=base.footnotes,
            available_height=available_fn_base,
            styles=self.styles,
            hyphenator=self.hyphenator,
            settings=self.settings,
            seen_chapters=self.seen_chapters,
        )

        count = base.count
        columns = base.columns
        text_height = base.text_height
        available_fn = available_fn_base
        deferred_notes: List[FootnoteEntry] = []

        # Step 1: add text+footnotes while both fit.
        while self.start_idx + count < self.stop_idx:
            candidate = count + 1
            cols, cand_height_raw = self.cache.columns_for(self.start_idx, candidate)
            cand_height_guess = _text_height_with_padding(
                cand_height_raw, True, self.settings
            )
            available_fn_guess = max(
                0.0, self.settings.body_height - self.header_height - cand_height_guess
            )
            new_items = self.items[self.start_idx : self.start_idx + candidate]
            new_notes = _footnotes_for_items(new_items)
            (
                placed_try,
                pending_try,
                rows_try,
                heights_try,
                lines_try,
                fn_height_try,
                seen_try,
            ) = _place_footnotes(
                pending=self.pending_notes,
                new_entries=new_notes,
                available_height=available_fn_guess,
                styles=self.styles,
                hyphenator=self.hyphenator,
                settings=self.settings,
                seen_chapters=self.seen_chapters,
            )
            cand_height = _text_height_with_padding(
                cand_height_raw, bool(rows_try), self.settings
            )
            available_fn = max(
                0.0, self.settings.body_height - self.header_height - cand_height
            )
            _debug(
                "[step1] cand=%d text_raw=%.2f text_pad=%.2f avail_text=%.2f "
                "avail_fn=%.2f fn_h=%.2f rows=%d pending_try=%d avail_fn_guess=%.2f"
                % (
                    candidate,
                    cand_height_raw,
                    cand_height,
                    self.available_text,
                    available_fn,
                    fn_height_try,
                    len(rows_try),
                    len(pending_try),
                    available_fn_guess,
                )
            )
            if pending_try or cand_height > self.available_text + EPSILON:
                break
            count = candidate
            columns = cols
            text_height = cand_height
            placed_notes, pending_notes = placed_try, pending_try
            fn_rows, fn_heights, fn_lines, fn_height = (
                rows_try,
                heights_try,
                lines_try,
                fn_height_try,
            )
            seen = seen_try

        # Step 2: fill remaining space with text-only, deferring those footnotes.
        body_limit = self.settings.body_height - self.header_height
        while self.start_idx + count < self.stop_idx:
            candidate = count + 1
            cand_cols, cand_height_raw = self.cache.columns_for(
                self.start_idx, candidate
            )
            cand_height = _text_height_with_padding(
                cand_height_raw, bool(fn_rows), self.settings
            )
            _debug(
                "[step2] cand=%d text_raw=%.2f text_pad=%.2f fn_h=%.2f "
                "body_limit=%.2f avail_text=%.2f"
                % (
                    candidate,
                    cand_height_raw,
                    cand_height,
                    fn_height,
                    body_limit,
                    self.available_text,
                )
            )
            if (
                cand_height + fn_height > body_limit + EPSILON
                or cand_height > self.available_text + EPSILON
            ):
                break
            new_line_items = self.items[
                self.start_idx + count : self.start_idx + candidate
            ]
            deferred_notes.extend(_footnotes_for_items(new_line_items))
            count = candidate
            columns = cand_cols
            text_height = cand_height

        return PagePlan(
            count=count,
            columns=columns,
            text_height=text_height,
            header_height=self.header_height,
            placed_notes=placed_notes,
            footnote_rows=fn_rows,
            footnote_heights=fn_heights,
            footnote_lines=fn_lines,
            footnote_height=fn_height,
            pending_notes=pending_notes + deferred_notes,
            seen_chapters=seen,
        )


def _place_footnotes(
    pending: Sequence[FootnoteEntry],
    new_entries: Sequence[FootnoteEntry],
    available_height: float,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    seen_chapters: set[str],
) -> tuple[
    List[FootnoteEntry],
    List[FootnoteEntry],
    List[tuple[str, str, str, Paragraph]],
    List[float],
    List[int],
    float,
    set[str],
]:
    """Add footnotes until height is exhausted.

    Returns placed entries, deferred entries, rendered rows, row heights, and total
    footnote height. Pending entries come first; new entries are appended.

    Args:
        pending: Footnotes waiting from previous pages.
        new_entries: Footnotes introduced by items on the current page.
        available_height: Space allowed for all footnotes on the page.
        styles: Paragraph styles used to render footnotes.
        hyphenator: Hyphenation helper for text.
        settings: Page geometry and spacing settings.
    Returns:
        placed entries, deferred entries, table rows, row heights, and the
        resulting footnote block height, plus the updated set of chapters that
        have been labeled.
    """

    entries = list(pending) + list(new_entries)
    placed: List[FootnoteEntry] = []
    rows: List[tuple[str, str, str, Paragraph]] = []
    heights: List[float] = []
    lines: List[int] = []
    seed_seen = set(seen_chapters)
    updated_seen = set(seed_seen)
    for idx, entry in enumerate(entries):
        test_entries = placed + [entry]
        test_rows, test_heights, test_lines, test_seen = _footnote_rows(
            test_entries, styles, hyphenator, settings, seen_chapters=seed_seen
        )
        if _footnote_height(test_heights, settings) <= available_height:
            placed = test_entries
            rows = test_rows
            heights = test_heights
            lines = test_lines
            updated_seen = test_seen
            continue
        return (
            placed,
            entries[idx:],
            rows,
            heights,
            lines,
            _footnote_height(heights, settings),
            updated_seen,
        )
    return (
        placed,
        [],
        rows,
        heights,
        lines,
        _footnote_height(heights, settings),
        updated_seen,
    )


def _next_break_index(current: int, breakpoints: Sequence[int], total: int) -> int:
    for bp in breakpoints:
        if bp > current:
            return bp
    return total


def _footnotes_for_items(items: Sequence[FlowItem]) -> List[FootnoteEntry]:
    notes: List[FootnoteEntry] = []
    for itm in items:
        if itm.is_verse:
            notes.extend(itm.footnotes)
    return notes


def _range_label(items: Sequence[FlowItem], book_lookup: Dict[str, Book]) -> str:
    verses = [itm for itm in items if itm.is_verse]
    if not verses:
        return ""
    first = verses[0]
    last = verses[-1]
    book = book_lookup.get(first.book_slug)
    book_name = book.abbrev or book.name if book else first.book_name
    if first.chapter == last.chapter:
        return f"{book_name} {first.chapter}:{first.verse}\u2013{last.verse}"
    return f"{book_name} {first.chapter}:{first.verse}\u2013{last.chapter}:{last.verse}"


def paginate_book(
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
) -> List[PageSlice]:
    """Paginate a single book into PageSlice objects."""

    all_items, header_map, breakpoints = _collect_items(
        book, styles, hyphenator, settings
    )
    pages: List[PageSlice] = []
    idx = 0
    pending_notes: List[FootnoteEntry] = []
    seen_chapters: set[str] = set()
    total_items = len(all_items)
    book_lookup = {book.slug: book}
    while idx < total_items:
        header_blocks = header_map.get(idx, [])
        header_height = _header_height(
            header_blocks, settings.body_width, settings.header_gap
        )
        max_idx = _next_break_index(idx, breakpoints, total_items)
        fitter = PageFitter(
            items=all_items,
            start_idx=idx,
            stop_idx=max_idx,
            header_height=header_height,
            settings=settings,
            styles=styles,
            hyphenator=hyphenator,
            pending_notes=pending_notes,
            seen_chapters=seen_chapters,
        )
        plan = fitter.plan()
        page_items = all_items[idx : idx + plan.count]
        pages.append(
            PageSlice(
                text_items=page_items,
                text_columns=plan.columns,
                text_height=plan.text_height,
                header_height=header_height,
                footnote_rows=plan.footnote_rows,
                footnote_row_heights=plan.footnote_heights,
                footnote_row_lines=plan.footnote_lines,
                footnote_entries=plan.placed_notes,
                header_flowables=header_blocks,
                range_label=_range_label(page_items, book_lookup),
                template_id=f"{book.slug}-p{len(pages)+1}",
                footnote_height=plan.footnote_height,
                # snapshot of chapters seen before laying out this page
                seen_chapters_in=set(seen_chapters),
            )
        )

        pending_notes = plan.pending_notes
        seen_chapters = plan.seen_chapters
        idx += plan.count
    return pages


def select_books(
    corpus: Sequence[StandardWork],
    book_slugs: Sequence[str] | None = None,
    max_books: int | None = None,
) -> List[StandardWork]:
    """Return a new corpus containing only the requested books.

    Args:
        corpus: Source corpus built from the scraper output.
        book_slugs: Optional list of book slugs (case-insensitive) to include.
            When omitted, all books are eligible.
        max_books: Optional per-standard-work cap applied after filtering by
            ``book_slugs``. Use ``None`` to keep every matching book.

    Returns:
        A list of ``StandardWork`` instances that reference the original ``Book``
        objects for the selected subset.

    Example:
        >>> nt = StandardWork(
        ...     name="New Testament",
        ...     slug="new-testament",
        ...     books=[
        ...         Book("new-testament", "John", "john", None, []),
        ...         Book("new-testament", "Luke", "luke", None, []),
        ...     ],
        ... )
        >>> selected = select_books([nt], book_slugs=["john"], max_books=None)
        >>> [book.slug for book in selected[0].books]
        ['john']
    """

    requested = {slug.lower() for slug in book_slugs} if book_slugs else None
    trimmed: List[StandardWork] = []
    found: set[str] = set()

    for work in corpus:
        books: List[Book] = []
        for book in work.books:
            include = requested is None or book.slug.lower() in requested
            if include:
                books.append(book)
                if requested is not None:
                    found.add(book.slug.lower())
            if requested is None and max_books is not None and len(books) >= max_books:
                break

        if requested is not None and max_books is not None:
            books = books[:max_books]

        if books:
            trimmed.append(
                StandardWork(
                    name=work.name,
                    slug=work.slug,
                    books=books,
                )
            )

    if requested:
        missing = requested - found
        assert not missing, f"Unknown book slugs: {', '.join(sorted(missing))}"

    return trimmed


def limit_books(corpus: Sequence[StandardWork], max_books: int) -> List[StandardWork]:
    """Return a trimmed copy of the corpus limited per standard work.

    Args:
        corpus: Source corpus built from the scraper output.
        max_books: Number of books to keep from each standard work.

    Returns:
        A list of ``StandardWork`` instances capped at ``max_books`` per work.

    Example:
        >>> limit_books(
        ...     [
        ...         StandardWork(
        ...             name="NT",
        ...             slug="new-testament",
        ...             books=[
        ...                 Book("new-testament", "John", "john", None, []),
        ...                 Book("new-testament", "Luke", "luke", None, []),
        ...             ],
        ...         )
        ...     ],
        ...     max_books=1,
        ... )[0].books[0].slug
        'john'
    """

    return select_books(corpus=corpus, max_books=max_books)


def _chapter_page_map(
    pages: Sequence[PageSlice], toc_pages: int = 1
) -> Dict[tuple[str, str], int]:
    """Map (book_slug, chapter) to the first page number where it appears."""

    mapping: Dict[tuple[str, str], int] = {}
    for idx, page in enumerate(pages, start=toc_pages + 1):
        for item in page.text_items:
            if item.is_verse:
                key = (item.book_slug, item.chapter)
                mapping.setdefault(key, idx)
    return mapping


def _code_map_from_metadata(metadata: Dict | None) -> Dict[str, str]:
    """Map short church URI codes to book slugs."""

    if not metadata:
        return {}
    mapping: Dict[str, str] = {}
    for work in metadata.get("structure", {}).values():
        for book_slug, data in work.get("books", {}).items():
            uri = data.get("churchUri")
            if not uri:
                continue
            code = uri.rstrip("/").split("/")[-1]
            mapping[code] = book_slug
    return mapping


def _toc_flowables(
    corpus: Sequence[StandardWork],
    chapter_pages: Dict[tuple[str, str], int],
    styles: Dict[str, ParagraphStyle],
) -> List[Paragraph]:
    """Build simple table of contents paragraphs."""

    entries: List[Paragraph] = [Paragraph("<b>Contents</b>", styles["header"])]
    for work in corpus:
        entries.append(Paragraph(work.name, styles["preface"]))
        for book in work.books:
            for chapter in book.chapters:
                page = chapter_pages.get((book.slug, chapter.number))
                if not page:
                    continue
                label = f"{book.name} {chapter.number}"
                entries.append(Paragraph(f"{label} ... {page}", styles["body"]))
    return entries


def _on_page_factory(label: str, font_name: str, settings: PageSettings):
    """Create an onPage callback that renders page number and range."""

    def draw(canvas, doc):
        canvas.saveState()
        canvas.bookmarkPage(f"page-{doc.page}")
        canvas.setFont(font_name, 9)
        y = settings.page_height - settings.margin_top + 8
        canvas.drawString(settings.margin_left, y, str(doc.page))
        canvas.drawRightString(settings.page_width - settings.margin_right, y, label)
        canvas.restoreState()

    return draw


def _extract_book_chapter(href: str) -> tuple[str, str] | None:
    """Pull (book_code, chapter) from a scripture href."""

    try:
        parts = [p for p in href.split("/") if p]
        idx = parts.index("scriptures")
        book_code = parts[idx + 2]
        chapter_part = parts[idx + 3] if len(parts) > idx + 3 else ""
        # chapter may be like '25?lang=eng&id=p1#p1'
        chapter = chapter_part.split("?")[0]
        return book_code, chapter
    except (ValueError, IndexError):
        return None


def _page_templates(
    page_slices: Sequence[PageSlice], settings: PageSettings, font_name: str
) -> List[PageTemplate]:
    """Build PageTemplate objects for TOC and content pages."""

    templates: List[PageTemplate] = []
    toc_frame = Frame(
        settings.margin_left,
        settings.margin_bottom,
        settings.body_width,
        settings.body_height,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="toc-frame",
    )
    templates.append(
        PageTemplate(
            id="toc",
            frames=[toc_frame],
            onPage=_on_page_factory("Contents", font_name, settings),
        )
    )
    for slice_ in page_slices:
        templates.append(
            PageTemplate(
                id=slice_.template_id,
                frames=_content_frames(slice_, settings),
                onPage=_on_page_factory(slice_.range_label, font_name, settings),
            )
        )
    return templates


def _content_frames(slice_: PageSlice, settings: PageSettings) -> List[Frame]:
    """Single frame; footnotes follow the text naturally in flow order."""

    return [
        Frame(
            settings.margin_left,
            settings.margin_bottom,
            settings.body_width,
            settings.body_height,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id=f"{slice_.template_id}-single",
            showBoundary=int(settings.debug_borders),
        )
    ]


def _story_for_pages(
    page_slices: Sequence[PageSlice],
    toc_flow: Sequence[Paragraph],
    settings: PageSettings,
) -> List:
    """Assemble the platypus story."""

    story: List = []
    story.extend(toc_flow)
    if page_slices:
        story.append(NextPageTemplate(page_slices[0].template_id))
    story.append(PageBreak())
    for idx, slice_ in enumerate(page_slices):
        story.extend(_page_flowables(slice_, settings))
        if idx + 1 < len(page_slices):
            story.append(NextPageTemplate(page_slices[idx + 1].template_id))
        story.append(PageBreak())
    if story:
        story.pop()
    return story


def _refresh_footnotes(
    page_slices: Sequence[PageSlice],
    chapter_pages: Dict[tuple[str, str], int],
    code_map: Dict[str, str],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
) -> None:
    """Rebuild footnote paragraphs now that page numbers are known."""

    for slice_ in page_slices:
        seed_seen = getattr(slice_, "seen_chapters_in", None)
        rows, heights, lines, _ = _footnote_rows(
            slice_.footnote_entries,
            styles,
            hyphenator,
            page_lookup=chapter_pages,
            code_map=code_map,
            settings=settings,
            seen_chapters=seed_seen,
        )
        slice_.footnote_rows = rows
        slice_.footnote_row_heights = heights
        slice_.footnote_row_lines = lines
        slice_.footnote_height = _footnote_height(heights, settings)


def _page_flowables(slice_: PageSlice, settings: PageSettings) -> List:
    """Flowables needed to render a single page slice."""

    flows: List = []
    flows.extend(slice_.header_flowables)
    if slice_.header_flowables:
        flows.append(Spacer(1, settings.header_gap))
    flows.append(
        _text_table(
            slice_.text_columns,
            settings,
            extend_separator=bool(slice_.footnote_rows),
        )
    )
    if slice_.footnote_rows:
        flows.append(_footnote_table(slice_, settings))
    return flows


def _column_bounds(heights: Sequence[float], columns: int) -> List[int]:
    """Return start indices for each column boundary."""

    if not heights:
        return [0] * (columns + 1)
    _, splits = optimal_partition(heights, min(columns, len(heights)))
    bounds = [0] + splits + [len(heights)]
    while len(bounds) < columns + 1:
        bounds.append(bounds[-1])
    return bounds[: columns + 1]


def _column_bounds_by_weights(weights: Sequence[int], columns: int) -> List[int]:
    """Return start indices using integer weights (e.g., line counts)."""

    if not weights:
        return [0] * (columns + 1)
    _, splits = optimal_partition(weights, min(columns, len(weights)))
    bounds = [0] + splits + [len(weights)]
    while len(bounds) < columns + 1:
        bounds.append(bounds[-1])
    return bounds[: columns + 1]


def _column_bounds_fill(weights: Sequence[int], columns: int) -> List[int]:
    """Sequentially fill columns left-to-right based on weight totals."""

    if not weights:
        return [0] * (columns + 1)
    total = sum(weights)
    target = max(1, -(-total // columns))  # ceiling division
    bounds = [0]
    acc = 0
    for idx, w in enumerate(weights, start=1):
        acc += w
        if acc >= target and len(bounds) < columns:
            bounds.append(idx)
            acc = 0
    bounds.append(len(weights))
    while len(bounds) < columns + 1:
        bounds.append(bounds[-1])
    return bounds[: columns + 1]


def _paragraphs_from_lines(
    lines: Sequence[FlowItem],
    styles: Dict[str, ParagraphStyle],
) -> List[Paragraph]:
    """Recombine line HTML into paragraphs per verse, honoring explicit <br/> splits."""

    if not lines:
        return []

    paragraphs: List[Paragraph] = []
    current: List[FlowItem] = [lines[0]]
    current_verse = lines[0].verse

    def flush(group: List[FlowItem]) -> None:
        if not group:
            return
        first = group[0]
        if first.style_name == "spacer":
            paragraphs.extend(item.paragraph for item in group)
            return
        if first.style_name == "chapter_heading_group":
            paragraphs.append(first.paragraph)
            return
        if first.style_name == "study":
            current_style = group[0].paragraph.style
            buffer = group[0].line_html
            for item in group[1:]:
                style = item.paragraph.style
                if style is current_style:
                    buffer = f"{buffer} {item.line_html}"
                    continue
                paragraphs.append(Paragraph(buffer, current_style))
                current_style = style
                buffer = item.line_html
            paragraphs.append(Paragraph(buffer, current_style))
            return
        if first.style_name.startswith("body"):
            ends_mid_verse = group[-1].verse_line_index < group[-1].verse_line_count - 1
            if ends_mid_verse:
                style_name = (
                    "body-justify-last"
                    if first.first_line
                    else "body-cont-justify-last"
                )
            else:
                style_name = "body" if first.first_line else "body-cont"
        else:
            style_name = first.style_name
        text = " ".join(item.line_html for item in group)
        paragraphs.append(Paragraph(text, styles[style_name]))

    for line in lines[1:]:
        if line.verse == current_verse:
            if line.segment_index != current[-1].segment_index:
                flush(current)
                current = [line]
            else:
                current.append(line)
            continue
        flush(current)
        current = [line]
        current_verse = line.verse
    flush(current)
    return paragraphs


def _layout_columns(
    items: Sequence[FlowItem],
    max_height: float,
    settings: PageSettings,
    styles: Dict[str, ParagraphStyle],
) -> Tuple[TextColumns, float, bool]:
    """Split wrapped lines into two columns with an even line count."""

    columns, table_height = _layout_columns_unfitted(items, settings, styles)
    fits = table_height <= max_height
    return columns, table_height, fits


def _layout_columns_unfitted(
    items: Sequence[FlowItem],
    settings: PageSettings,
    styles: Dict[str, ParagraphStyle],
) -> Tuple[TextColumns, float]:
    """Return column layout and height without performing a fit check."""

    def _line_weight(itm: FlowItem) -> int:
        para = itm.paragraph
        if hasattr(para, "logical_lines"):
            try:
                return max(1, int(para.logical_lines))
            except Exception:
                return 1
        return 1

    weights = [_line_weight(itm) for itm in items]
    total_weight = sum(weights)
    target = (total_weight + 1) // 2
    split_idx = 0
    running = 0
    for idx, w in enumerate(weights):
        running += w
        split_idx = idx + 1
        if running >= target:
            break

    left_lines = items[:split_idx]
    right_lines = items[split_idx:]
    left_paras = _paragraphs_from_lines(left_lines, styles)
    right_paras = _paragraphs_from_lines(right_lines, styles)
    temp_columns = TextColumns(left_paras, right_paras, 0.0)
    table = _text_table(temp_columns, settings)
    _, table_height = table.wrap(settings.body_width, 10_000)
    temp_columns.height = table_height
    return temp_columns, table_height


@dataclass(slots=True)
class TextColumns:
    left: List[Paragraph]
    right: List[Paragraph]
    height: float


class FootnoteBlock(Flowable):
    """Wrap a footnote table and draw column separator lines the full height."""

    def __init__(
        self,
        table: Table,
        line_positions: Sequence[float],
        line_width: float,
        line_color: colors.Color,
        top_padding: float,
    ) -> None:
        super().__init__()
        self.table = table
        self.line_positions = tuple(line_positions)
        self.line_width = line_width
        self.line_color = line_color
        self.top_padding = top_padding
        self.width = 0.0
        self.height = 0.0

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        """Delegate wrap to the inner table and capture its size."""

        self.width, self.height = self.table.wrap(availWidth, availHeight)
        return self.width, self.height

    def draw(self) -> None:
        """Draw the table then overlay full-height separator rules."""

        self.table.drawOn(self.canv, 0, 0)
        self.canv.saveState()
        self.canv.setStrokeColor(self.line_color)
        self.canv.setLineWidth(self.line_width)
        for x in self.line_positions:
            self.canv.line(x, 0, x, self.height)
        self.canv.line(0, self.height, self.width, self.height)
        self.canv.restoreState()


def _text_table(
    columns: TextColumns, settings: PageSettings, extend_separator: bool = False
) -> Table:
    """Render two text columns in reading order."""

    col_width = settings.text_column_width()
    left_flow = columns.left if columns.left else [Spacer(1, 0)]
    right_flow = columns.right if columns.right else [Spacer(1, 0)]
    bottom_padding = settings.column_gap / 2 if extend_separator else 0
    table = Table(
        [[left_flow, right_flow]], colWidths=[col_width, col_width], hAlign="LEFT"
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), bottom_padding),
                ("RIGHTPADDING", (0, 0), (0, 0), settings.column_gap / 2),
                ("LEFTPADDING", (1, 0), (1, 0), settings.column_gap / 2),
                ("LINEBEFORE", (1, 0), (1, 0), 0.4, colors.lightgrey),
                *(
                    [("BOX", (0, 0), (-1, -1), 0.4, colors.red)]
                    if settings.debug_borders
                    else []
                ),
            ]
        )
    )
    return table


def _footnote_table(slice_: PageSlice, settings: PageSettings):
    """Render footnotes as a tight three-column table."""

    if not slice_.footnote_rows:
        return Spacer(1, 0)

    include_chapter = any(bool(ch) for ch, _, _, _ in slice_.footnote_rows)
    col_widths_dynamic = _footnote_column_widths(
        slice_.footnote_rows, include_chapter, settings
    )
    bounds = _column_bounds_fill(slice_.footnote_row_lines, 3)
    col_width = settings.footnote_column_width()
    inner_widths = col_widths_dynamic if include_chapter else col_widths_dynamic[1:]

    columns = []
    for start, end in zip(bounds[:-1], bounds[1:]):
        segment = slice_.footnote_rows[start:end]
        seg_heights = slice_.footnote_row_heights[start:end]
        if not segment:
            columns.append(Spacer(1, 0))
            continue
        if include_chapter:
            data = [[ch, vs, letter, para] for ch, vs, letter, para in segment]
        else:
            data = [[vs, letter, para] for _, vs, letter, para in segment]
        tbl = Table(data, colWidths=inner_widths, rowHeights=seg_heights, hAlign="LEFT")
        style_entries: List[tuple] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), settings.footnote_row_padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), settings.footnote_row_padding),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, -1), settings.font_name),
        ]
        if include_chapter:
            style_entries.append(("FONTNAME", (0, 0), (0, -1), settings.font_bold_name))
            style_entries.append(("ALIGN", (0, 0), (0, -1), "RIGHT"))  # chapter
            style_entries.append(("ALIGN", (1, 0), (1, -1), "RIGHT"))  # verse
            style_entries.append(("ALIGN", (2, 0), (2, -1), "LEFT"))  # letter
            style_entries.append(
                ("RIGHTPADDING", (2, 0), (2, -1), settings.footnote_letter_gap)
            )
        else:
            style_entries.append(("ALIGN", (0, 0), (0, -1), "RIGHT"))  # verse
            style_entries.append(("ALIGN", (1, 0), (1, -1), "LEFT"))  # letter
            style_entries.append(
                ("RIGHTPADDING", (1, 0), (1, -1), settings.footnote_letter_gap)
            )
            style_entries.append(("LEFTPADDING", (0, 0), (0, -1), 10))

        tbl.setStyle(TableStyle(style_entries))
        columns.append(tbl)

    col_widths = (
        col_width + settings.column_gap / 2,
        col_width + settings.column_gap,
        col_width + settings.column_gap / 2,
    )
    outer = Table(
        [[columns[0], columns[1], columns[2]]], colWidths=col_widths, hAlign="LEFT"
    )
    styles: List[tuple] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), settings.column_gap / 2),
        ("LEFTPADDING", (1, 0), (1, -1), settings.column_gap / 2),
        ("RIGHTPADDING", (1, 0), (1, -1), settings.column_gap / 2),
        ("LEFTPADDING", (2, 0), (2, -1), settings.column_gap / 2),
        ("RIGHTPADDING", (2, 0), (2, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), settings.column_gap / 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if settings.debug_borders:
        styles.append(("BOX", (0, 0), (-1, -1), 0.4, colors.blue))
    outer.setStyle(TableStyle(styles))

    line_xs = [col_widths[0], col_widths[0] + col_widths[1]]
    top_padding = settings.column_gap / 2
    return FootnoteBlock(
        table=outer,
        line_positions=line_xs,
        line_width=0.4,
        line_color=colors.lightgrey,
        top_padding=top_padding,
    )


def _footnote_flowable(
    text: str, style: ParagraphStyle, width: float, settings: PageSettings
) -> tuple[Paragraph, float]:
    """Create a Paragraph flowable for a single footnote segment."""

    para = Paragraph(text, style)
    return para, measure_height(para, width)


def _footnote_column_widths(
    rows: Sequence[tuple[object, str, str, object]],
    include_chapter: bool,
    settings: PageSettings,
) -> tuple[float, float, float, float]:
    """Compute dynamic footnote column widths based on content."""

    font = settings.font_name
    font_ch = settings.font_bold_name or settings.font_name
    size = settings.footnote_font_size
    min_w = 6.0

    def _plain(val):
        if hasattr(val, "getPlainText"):
            return val.getPlainText()
        if isinstance(val, Paragraph):
            return val.getPlainText()
        if isinstance(val, str):
            if "<" in val:
                return BeautifulSoup(val, "html.parser").get_text()
            return val
        return str(val) if val else ""

    max_vs = max(
        (pdfmetrics.stringWidth(_plain(vs), font, size) for _, vs, _, _ in rows if vs),
        default=0.0,
    )
    max_lt = max(
        (pdfmetrics.stringWidth(_plain(lt), font, size) for _, _, lt, _ in rows if lt),
        default=0.0,
    )

    if include_chapter:
        max_ch = max(
            (
                pdfmetrics.stringWidth(_plain(ch), font_ch, size)
                for ch, _, _, _ in rows
                if ch
            ),
            default=0.0,
        )
        ch_w = max(min_w, max_ch + 1.0)
    else:
        ch_w = 0.0

    vs_w = max(min_w, max_vs + 1.0)
    lt_w = max(min_w, max_lt + settings.footnote_letter_gap)
    txt_w = max(24.0, settings.footnote_column_width() - (ch_w + vs_w + lt_w))
    return ch_w, vs_w, lt_w, txt_w


def build_pdf(
    corpus: Sequence[StandardWork],
    output_path: Path,
    settings: PageSettings | None = None,
    max_books: int | None = 2,
    metadata: Dict | None = None,
    include_books: Sequence[str] | None = None,
) -> None:
    """Render the provided corpus into a PDF.

    Args:
        corpus: Sequence of ``StandardWork`` instances to typeset.
        output_path: Destination file for the generated PDF.
        settings: Optional ``PageSettings`` override; defaults to Palatino-based
            defaults when omitted.
        max_books: Per-standard-work cap used when ``include_books`` is not set.
            Use ``None`` to disable the cap.
        metadata: Optional JSON metadata produced by the scraper for code/footnote
            lookups.
        include_books: Optional list of book slugs to render. When provided, the
            selection overrides ``max_books``.

    Returns:
        None. Writes the generated PDF to ``output_path``.

    Example:
        >>> build_pdf(corpus, Path("output/john.pdf"), include_books=["john"])  # doctest: +SKIP
    """

    settings = settings or PageSettings()
    settings.debug_borders = True
    font_name = register_palatino()
    settings.font_name = font_name
    settings.font_bold_name = "Palatino-Bold"
    styles = build_styles(font_name)
    hyphenator = Pyphen(lang="en_US")
    trimmed = select_books(
        corpus=corpus,
        book_slugs=include_books,
        max_books=None if include_books else max_books,
    )

    page_slices: List[PageSlice] = []
    for work in trimmed:
        for book in work.books:
            page_slices.extend(paginate_book(book, styles, hyphenator, settings))

    chapter_pages = _chapter_page_map(page_slices)
    _refresh_footnotes(
        page_slices,
        chapter_pages,
        _code_map_from_metadata(metadata),
        styles,
        hyphenator,
        settings,
    )
    toc_flow = _toc_flowables(trimmed, chapter_pages, styles)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=(settings.page_width, settings.page_height),
        leftMargin=settings.margin_left,
        rightMargin=settings.margin_right,
        topMargin=settings.margin_top,
        bottomMargin=settings.margin_bottom,
    )
    doc.addPageTemplates(_page_templates(page_slices, settings, font_name))
    story = _story_for_pages(page_slices, toc_flow, settings)
    doc.build(story)


def _verse_markup(verse: Verse) -> str:
    """Return HTML markup for a verse with its number."""

    number = verse.number or ""
    html = f"<span><b>{number}</b></span> {verse.html}"
    return _italicize_sup_letters(
        html, italic_font=getattr(_verse_markup, "italic_font_name", None)
    )


def _paragraph_from_html(
    html: str,
    style: ParagraphStyle,
    hyphenator: Pyphen,
    *,
    insert_hair_space: bool = True,
) -> Paragraph:
    """Create a Paragraph with hyphenated text."""

    sanitized = _collapse_space_after_sup(_strip_attributes(html))
    hyphenated = hyphenate_html(
        sanitized, hyphenator, insert_hair_space=insert_hair_space
    )
    para = Paragraph(hyphenated, style)
    setattr(para, "_orig_html", hyphenated)
    return para


def _line_has_visible_text_after(line_html: str, idx: int) -> bool:
    """Return True when non-whitespace content follows the given index."""

    cursor = idx + 1
    while cursor < len(line_html):
        ch = line_html[cursor]
        if ch == "<":
            closing = line_html.find(">", cursor + 1)
            if closing == -1:
                break
            cursor = closing + 1
            continue
        if ch.isspace():
            cursor += 1
            continue
        return True
    return False


def _unused_hairspace_positions(
    line_htmls: List[str], hyphenated_html: str
) -> List[int]:
    """Return hair space indexes after dashes that still have trailing text."""

    dash_pairs: List[tuple[str, int]] = []
    src = hyphenated_html
    for idx in range(len(src) - 1):
        if src[idx] in DASH_CHARS and src[idx + 1] == HAIR_SPACE:
            dash_pairs.append((src[idx], idx + 1))
    if not dash_pairs:
        return []
    removal: List[int] = []
    pair_idx = 0
    for line_html in line_htmls:
        pos = 0
        while pos < len(line_html) and pair_idx < len(dash_pairs):
            if line_html[pos] == dash_pairs[pair_idx][0]:
                if _line_has_visible_text_after(line_html, pos):
                    removal.append(dash_pairs[pair_idx][1])
                pair_idx += 1
            pos += 1
        if pair_idx >= len(dash_pairs):
            break
    return removal


def _strip_characters_at_positions(text: str, indexes: List[int]) -> str:
    """Drop characters from ``text`` at the given positions."""

    if not indexes:
        return text
    chars = list(text)
    for index in sorted(indexes, reverse=True):
        if 0 <= index < len(chars):
            del chars[index]
    return "".join(chars)


def _wrap_paragraph(
    html: str, style: ParagraphStyle, hyphenator: Pyphen, width: float
) -> tuple[Paragraph, List[str]]:
    """Return a paragraph and lines, rewrapping if hair spaces were unused.

    Example:
        >>> hyphenator = Pyphen(lang="en_US")
        >>> style = ParagraphStyle("Body")
        >>> _wrap_paragraph("<p>test—text</p>", style, hyphenator, 200)
    """

    para = _paragraph_from_html(html, style, hyphenator, insert_hair_space=True)
    line_htmls = _line_fragments(para, width)
    hyphenated_html = getattr(para, "_orig_html", "")
    unused_positions = (
        _unused_hairspace_positions(line_htmls, hyphenated_html)
        if hyphenated_html
        else []
    )
    if unused_positions:
        cleaned_html = _strip_characters_at_positions(hyphenated_html, unused_positions)
        para = Paragraph(cleaned_html, style)
        setattr(para, "_orig_html", cleaned_html)
        line_htmls = _line_fragments(para, width)
    return para, line_htmls


def _ensure_verse_number_span(line_html: str, verse_number: str | None) -> str:
    """Keep the verse number wrapped in a span so it survives wrapping."""

    if not verse_number or "<span><b>" in line_html:
        return line_html
    stripped = line_html.lstrip()
    if not stripped.startswith(verse_number):
        return line_html
    leading = line_html[: len(line_html) - len(stripped)]
    remainder = stripped[len(verse_number) :]
    gap = ""
    if remainder and not remainder[0].isspace() and not remainder.startswith("&nbsp;"):
        gap = " "
    return f"{leading}<span><b>{verse_number}</b></span>{gap}{remainder}"


def _strip_attributes(html: str) -> str:
    """Remove non-essential HTML attributes."""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        if tag.name == "a" and tag.has_attr("href"):
            href = tag["href"]
            if isinstance(href, str) and href.startswith("#"):
                tag.unwrap()
                continue
            tag.attrs = {"href": href}
        elif tag.name == "font":
            allowed = {
                k: v for k, v in tag.attrs.items() if k in {"name", "size", "color"}
            }
            tag.attrs = allowed
        else:
            tag.attrs = {}
    text = soup.decode_contents()
    # If a superscript is immediately between two letters, insert a space before it
    # so it prefixes the following word (e.g., "beginningbGod" -> "beginning bGod").
    text = re.sub(r"(?<=[A-Za-z])(<sup>[^<]+</sup>)(?=[A-Za-z])", r" \1", text)
    return text


DEBUG_PAGINATION = os.getenv("DEBUG_PAGINATION", "0") not in {"", "0", "false", "False"}
EPSILON = 1e-4


def _debug(msg: str) -> None:
    if DEBUG_PAGINATION:
        print(msg)


def _collapse_space_after_sup(html: str) -> str:
    """Remove whitespace inserted after <sup> markers before the next word."""

    return re.sub(r"</sup>\s+(?=[A-Za-z0-9])", "</sup>", html)


def _apply_hebrew_font(html: str, hebrew_font: str | None) -> str:
    """Wrap Hebrew characters with a font tag so they use a glyph-capable font.

    Args:
        html: Raw HTML string that may contain Hebrew code points.
        hebrew_font: Name of the registered font to apply; when None, the HTML
            is returned unchanged.
    Returns:
        HTML string with Hebrew ranges wrapped in <font name="..."> tags.
    """

    if not hebrew_font:
        return html
    return re.sub(
        r"([\u0590-\u05FF]+)",
        rf'<font name="{hebrew_font}">\1</font>',
        html,
    )


def _italicize_sup_letters(html: str, italic_font: str | None = None) -> str:
    """Wrap single-letter superscripts in italics (optionally forcing a font)."""

    def repl(match: re.Match[str]) -> str:
        inner = match.group(2)
        plain = re.sub(r"<[^>]+>", "", inner)
        if plain and plain.strip().isalpha() and len(plain.strip()) == 1:
            letter = plain.strip()
            if italic_font:
                return f'{match.group(1)}<font name="{italic_font}"><i>{letter}</i></font>{match.group(3)}'
            return f"{match.group(1)}<i>{letter}</i>{match.group(3)}"
        return match.group(0)

    return re.sub(r"(<sup[^>]*>)(.*?)(</sup>)", repl, html, flags=re.DOTALL)


def _split_on_breaks(html: str) -> List[str]:
    """Split an HTML fragment on <br/> boundaries, preserving empty segments."""

    return re.split(r"<br\s*/?>", html, flags=re.IGNORECASE)


def _footnote_letters(html: str) -> List[str]:
    """Return lowercase footnote letters found in ``<sup>`` tags within HTML."""

    matches = re.findall(r"<sup[^>]*>(.*?)</sup>", html)
    letters = [re.sub(r"<[^>]+>", "", m) for m in matches]
    return [
        ch.lower()
        for ch in letters
        if ch and ch.strip().isalpha() and len(ch.strip()) == 1
    ]


def _continuation_style(style: ParagraphStyle) -> ParagraphStyle:
    """Return a copy of a style with no first-line indent for wrapped lines."""

    if style.name.endswith("-cont"):
        return style
    return ParagraphStyle(
        f"{style.name}-cont",
        parent=style,
        firstLineIndent=0,
    )


def _line_fragments(para: Paragraph, width: float) -> List[str]:
    """Return a list of HTML strings, one per wrapped line of the paragraph.

    This uses ReportLab's own line breaking (via ``wrap``) to ensure the split
    matches the actual layout. Inline styling is reconstructed from word
    fragments so markers like <sup> stay intact.
    """

    para.allowOrphans = 1
    para.allowWidows = 1
    para.wrap(width, 10_000)
    if not hasattr(para, "blPara"):
        return [para.text]
    base_font = getattr(para.style, "fontName", "")

    def word_markup(word) -> str:
        if hasattr(word, "text"):
            txt = word.text
        elif isinstance(word, str):
            txt = word
        else:
            return ""
        hrefs = getattr(word, "link", [])
        if hrefs:
            href = hrefs[0][1]
            txt = f'<a href="{href}">{txt}</a>'
        fname = getattr(word, "fontName", "")
        if "Bold" in fname or getattr(word, "bold", 0):
            txt = f"<b>{txt}</b>"
        if "Italic" in fname or "Oblique" in fname or getattr(word, "italic", 0):
            txt = f"<i>{txt}</i>"
        rise = getattr(word, "rise", 0)
        plain = re.sub(r"<[^>]+>", "", txt)
        if rise > 0:
            if plain and plain.strip().isalpha() and len(plain.strip()) == 1:
                txt = f"<sup><i>{plain.strip()}</i></sup>"
            else:
                txt = f"<sup>{txt}</sup>"
        elif rise < 0:
            txt = f"<sub>{txt}</sub>"
        if fname and fname != base_font:
            txt = f'<font name="{fname}">{txt}</font>'
        return txt

    lines: List[str] = []
    for line in para.blPara.lines:
        words_seq = getattr(line, "words", None)
        if words_seq is None:
            if isinstance(line, tuple) and len(line) == 2 and isinstance(line[1], list):
                words_seq = line[1]
            elif isinstance(line, (list, tuple)) and line:
                candidate = line[0]
                if hasattr(candidate, "__iter__") and not isinstance(
                    candidate, (str, bytes)
                ):
                    words_seq = candidate
                else:
                    words_seq = line
            else:
                words_seq = []
        words = [word_markup(w) for w in words_seq]
        # Preserve spacing: if words already include space fragments, use direct join;
        # otherwise insert a space between tokens.
        if all(isinstance(ws, str) and " " not in ws for ws in words):
            html_line = " ".join(words)
        else:
            html_line = "".join(words)
        if not html_line and hasattr(line, "text"):
            html_line = str(getattr(line, "text", "")) or ""
        html_line = _collapse_space_after_sup(html_line)
        lines.append(html_line)
    return lines or [para.text]


def _line_items_for_chapter(
    chapter: Chapter,
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    column_width: float,
    inline_preface: bool,
    include_chapter_heading: bool,
) -> List[FlowItem]:
    """Convert a chapter into line-sized FlowItems ready for pagination.

    Args:
        chapter: Chapter to render.
        book: Parent book information.
        styles: Paragraph styles for the document.
        hyphenator: Hyphenation helper for body text.
        column_width: Target column width for wrapping.
        inline_preface: Whether to inline preface blocks for this chapter.
        include_chapter_heading: Whether to render an in-column chapter heading.
    Returns:
        A list of FlowItems where each verse is split into single-line units.
    """

    items: List[FlowItem] = []
    inner_width = column_width

    footnotes_by_verse: Dict[str, List[FootnoteEntry]] = {}
    for entry in chapter.footnotes:
        footnotes_by_verse.setdefault(entry.verse, []).append(entry)

    verse_lookup = {v.compare_id: v for v in chapter.verses}
    sup_italic_font = getattr(styles.get("body"), "italic_font_name", None)
    setattr(_verse_markup, "italic_font_name", sup_italic_font)

    para_counter = 0

    def _append_lines(html: str, style, style_name: str, paragraph_key: str) -> None:
        para, line_htmls = _wrap_paragraph(html, style, hyphenator, inner_width)
        for idx, line_html in enumerate(line_htmls):
            line_para = Paragraph(line_html, style)
            items.append(
                FlowItem(
                    paragraph=line_para,
                    height=measure_height(line_para, inner_width),
                    line_html=line_html,
                    style_name=style_name,
                    first_line=idx == 0,
                    standard_work=chapter.standard_work,
                    book_slug=book.slug,
                    book_name=book.name,
                    chapter=chapter.number,
                    verse=paragraph_key,
                    footnotes=[],
                )
            )

    def _insert_spacer(height: float, paragraph_key: str) -> None:
        """Add a blank FlowItem to preserve vertical spacing."""

        if height <= 0:
            return
        spacer = Spacer(1, height)
        items.append(
            FlowItem(
                paragraph=spacer,
                height=measure_height(spacer, inner_width),
                line_html="",
                style_name="spacer",
                first_line=False,
                standard_work=chapter.standard_work,
                book_slug=book.slug,
                book_name=book.name,
                chapter=chapter.number,
                verse=paragraph_key,
                footnotes=[],
            )
        )

    if include_chapter_heading:
        heading_text = f"CHAPTER {chapter.number}"
        heading_para = Paragraph(heading_text, styles["chapter_heading"])
        heading_height = measure_height(heading_para, inner_width)
        spacer_before = Spacer(1, heading_height * 0.5)
        spacer_after = Spacer(1, heading_height * 0.5)
        grouped = StackedFlowable(
            [spacer_before, heading_para, spacer_after], logical_lines=3
        )
        items.append(
            FlowItem(
                paragraph=grouped,
                height=measure_height(grouped, inner_width),
                line_html=heading_text,
                style_name="chapter_heading_group",
                first_line=True,
                standard_work=chapter.standard_work,
                book_slug=book.slug,
                book_name=book.name,
                chapter=chapter.number,
                verse=f"chapter-{chapter.number}",
                footnotes=[],
            )
        )

    for para_dict in chapter.paragraphs:
        p_type = para_dict.get("type")
        if p_type == "verse":
            verse = verse_lookup.get(para_dict.get("compareId"))
            if verse is None:
                continue
            segments = _split_on_breaks(_verse_markup(verse))
            footnote_map = {
                entry.letter.lower(): entry
                for entry in footnotes_by_verse.get(verse.number, [])
            }
            assigned_letters: set[str] = set()
            for seg_idx, segment_html in enumerate(segments):
                if segment_html.strip() == "":
                    spacer_para = Paragraph("&nbsp;", styles["body-cont"])
                    items.append(
                        FlowItem(
                            paragraph=spacer_para,
                            height=measure_height(spacer_para, inner_width),
                            line_html="&nbsp;",
                            style_name="body-cont",
                            first_line=False,
                            standard_work=chapter.standard_work,
                            book_slug=book.slug,
                            book_name=book.name,
                            chapter=chapter.number,
                            verse=verse.number,
                            footnotes=[],
                            segment_index=seg_idx,
                            verse_line_index=0,
                            verse_line_count=1,
                        )
                    )
                    continue
                _, line_htmls = _wrap_paragraph(
                    segment_html, styles["body"], hyphenator, inner_width
                )
                total_lines = len(line_htmls)
                for line_idx, line_html in enumerate(line_htmls):
                    is_first_line = seg_idx == 0 and line_idx == 0
                    style = styles["body"] if is_first_line else styles["body-cont"]
                    if is_first_line:
                        line_html = _ensure_verse_number_span(
                            line_html, verse.number if verse else None
                        )
                    line_para = Paragraph(line_html, style)
                    letters = _footnote_letters(line_html)
                    notes_for_line = [
                        footnote_map[lt]
                        for lt in letters
                        if lt in footnote_map and lt not in assigned_letters
                    ]
                    assigned_letters.update(lt for lt in letters if lt in footnote_map)
                    items.append(
                        FlowItem(
                            paragraph=line_para,
                            height=measure_height(line_para, inner_width),
                            line_html=line_html,
                            style_name="body" if is_first_line else "body-cont",
                            first_line=is_first_line,
                            standard_work=chapter.standard_work,
                            book_slug=book.slug,
                            book_name=book.name,
                            chapter=chapter.number,
                            verse=verse.number,
                            footnotes=notes_for_line,
                            segment_index=seg_idx,
                            verse_line_index=line_idx,
                            verse_line_count=total_lines,
                        )
                    )

            if footnote_map and assigned_letters != set(footnote_map):
                unmatched = [
                    entry
                    for key, entry in footnote_map.items()
                    if key not in assigned_letters
                ]
                for entry in unmatched:
                    items[-1].footnotes.append(entry)
        elif p_type == "section-title":
            para_counter += 1
            if not items:
                _insert_spacer(
                    styles["section"].spaceBefore or 0, f"{p_type}-{para_counter}-lead"
                )
            section_html = para_dict.get("contentHtml", "")
            hebrew_font = getattr(styles["section"], "hebrew_font_name", None)
            section_html = _apply_hebrew_font(section_html, hebrew_font)
            _append_lines(
                section_html, styles["section"], "section", f"{p_type}-{para_counter}"
            )
            _insert_spacer(
                styles["section"].spaceAfter or 0, f"{p_type}-{para_counter}-trail"
            )
        elif p_type == "study-paragraph":
            para_counter += 1
            study_html = para_dict.get("contentHtml", "")
            _, line_htmls = _wrap_paragraph(
                study_html, styles["study"], hyphenator, inner_width
            )

            grouped_with_heading = (
                line_htmls and items and items[-1].style_name == "chapter_heading_group"
            )
            is_single = len(line_htmls) == 1

            if grouped_with_heading:
                heading_item = items.pop()
                heading_lines = getattr(heading_item.paragraph, "logical_lines", 1)
                first_line_html = line_htmls.pop(0)
                # Single-line study: do not force justify.
                first_style = styles["study"] if is_single else styles["study_first"]
                first_line_para = Paragraph(first_line_html, first_style)
                grouped = StackedFlowable(
                    [heading_item.paragraph, first_line_para],
                    logical_lines=heading_lines,  # HERE
                )
                items.append(
                    FlowItem(
                        paragraph=grouped,
                        height=measure_height(grouped, inner_width),
                        line_html=f"{heading_item.line_html} + {first_line_html}",
                        style_name="chapter_heading_group",
                        first_line=True,
                        standard_work=heading_item.standard_work,
                        book_slug=heading_item.book_slug,
                        book_name=heading_item.book_name,
                        chapter=heading_item.chapter,
                        verse=heading_item.verse,
                        footnotes=[],
                    )
                )

            for idx, line_html in enumerate(line_htmls):
                is_last = idx == len(line_htmls) - 1
                style = (
                    styles["study"] if is_single or is_last else styles["study_first"]
                )
                line_para = Paragraph(line_html, style)
                items.append(
                    FlowItem(
                        paragraph=line_para,
                        height=measure_height(line_para, inner_width),
                        line_html=line_html,
                        style_name="study",
                        first_line=idx == 0 and not grouped_with_heading,
                        standard_work=chapter.standard_work,
                        book_slug=book.slug,
                        book_name=book.name,
                        chapter=chapter.number,
                        verse=f"{p_type}-{para_counter}",
                        footnotes=[],
                    )
                )
            # Add a full-height padding line only after the final portion.
            padding_para = Paragraph("&nbsp;", styles["body-cont"])
            padding_para.logical_lines = 1
            items.append(
                FlowItem(
                    paragraph=padding_para,
                    height=measure_height(padding_para, inner_width),
                    line_html="&nbsp;",
                    style_name="body-cont",
                    first_line=False,
                    standard_work=chapter.standard_work,
                    book_slug=book.slug,
                    book_name=book.name,
                    chapter=chapter.number,
                    verse=f"{p_type}-{para_counter}-padding",
                    footnotes=[],
                )
            )
        else:
            # skip other types; titles handled separately
            continue
    return items


def _full_width_header(
    chapter: Chapter, styles: Dict[str, ParagraphStyle], hyphenator: Pyphen
) -> List[Paragraph]:
    """Build full-width header blocks for the top of a page."""

    blocks: List[Paragraph] = []
    for block_type, html in chapter.header_blocks:
        style = styles["header"] if "title" in block_type else styles["preface"]
        para = _paragraph_from_html(html, style, hyphenator)
        if getattr(style, "backColor", None) is None:
            debug_style = ParagraphStyle(
                name=(
                    style.name + "-debug"
                    if not style.name.endswith("-debug")
                    else style.name
                ),
                parent=style,
                borderWidth=0.6,
                borderColor=colors.green,
                borderPadding=2,
            )
            para = Paragraph(para.text, debug_style)
        blocks.append(para)
    return blocks


def _footnote_rows(
    entries: Sequence[FootnoteEntry],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    page_lookup: Dict[tuple[str, str], int] | None = None,
    code_map: Dict[str, str] | None = None,
    seen_chapters: set[str] | None = None,
) -> Tuple[List[tuple[str, str, str, Paragraph]], List[float], List[int], set[str]]:
    """Create footnote table rows and their heights."""

    rows_raw: List[tuple[str, str, str, str]] = []
    seen_chapters = set(seen_chapters) if seen_chapters else set()
    last_ch = None
    last_vs = None

    for entry in entries:
        first_in_ch = entry.chapter not in seen_chapters
        ch_raw = entry.chapter if first_in_ch else ""
        vs = entry.verse if (entry.chapter, entry.verse) != (last_ch, last_vs) else ""
        base_segments = entry.segments if entry.segments else [entry.text]
        segments = []
        for seg in base_segments:
            rewritten = _rewrite_entry_text(seg, hyphenator, page_lookup, code_map)
            if rewritten:
                segments.append(rewritten)
        if not segments:
            segments = [""]

        for seg_idx, seg in enumerate(segments):
            rows_raw.append(
                (
                    ch_raw if seg_idx == 0 else "",
                    vs if seg_idx == 0 else "",
                    entry.letter if seg_idx == 0 else "",
                    seg,
                )
            )
        seen_chapters.add(entry.chapter)
        last_ch, last_vs = entry.chapter, entry.verse

    include_chapter = any(ch for ch, _, _, _ in rows_raw)
    ch_w, vs_w, lt_w, txt_w = _footnote_column_widths(
        rows_raw, include_chapter, settings
    )

    rows: List[tuple[object, str, str, Paragraph]] = []
    heights: List[float] = []
    line_counts: List[int] = []
    for ch_raw, vs, letter, seg in rows_raw:
        flow, flow_height = _footnote_flowable(seg, styles["footnote"], txt_w, settings)
        height = flow_height + 2 * settings.footnote_row_padding
        ch_cell = Paragraph(ch_raw, styles["footnote_ch"]) if ch_raw else ""
        letter_cell = Paragraph(letter, styles["footnote_letter"]) if letter else ""
        rows.append((ch_cell, vs, letter_cell, flow))
        heights.append(height)
        flow.wrap(txt_w, 10_000)
        if hasattr(flow, "blPara") and hasattr(flow.blPara, "lines"):
            line_counts.append(len(flow.blPara.lines))
        else:
            line_counts.append(1)

    return rows, heights, line_counts, seen_chapters


def _rewrite_entry_text(
    html: str,
    hyphenator: Pyphen,
    page_lookup: Dict[tuple[str, str], int] | None,
    code_map: Dict[str, str] | None,
) -> str:
    """Convert entry HTML into hyphenated text with adjusted links."""

    soup = BeautifulSoup(html, "html.parser")

    if page_lookup and code_map:
        for anchor in soup.find_all("a", href=True):
            target = _extract_book_chapter(anchor["href"])
            if not target:
                if anchor["href"].startswith("#"):
                    anchor.unwrap()
                continue
            book_slug = code_map.get(target[0])
            if not book_slug:
                continue
            page = page_lookup.get((book_slug, target[1]))
            if page:
                anchor["href"] = f"#page-{page}"

    html_out = soup.decode_contents()
    html_out = htmllib.unescape(html_out)
    html_out = html_out.replace("\u00a0", " ")
    html_out = _collapse_space_after_sup(html_out)
    # Insert a space when a word is glued to a following anchor (e.g., 'see<a...>').
    html_out = re.sub(r"([A-Za-z])<a\b", r"\1 <a", html_out)
    # Insert a space when a period is glued directly to a following anchor.
    html_out = re.sub(r"\.\s*<a\b", ". <a", html_out)
    html_out = re.sub(r"\b(TG|HEB)\s*(?=[A-Za-z])", r"\1 ", html_out)
    html_out = re.sub(r"\s{2,}", " ", html_out)

    return hyphenate_html(html_out, hyphenator)


def _footnote_height(heights: Sequence[float], settings: PageSettings) -> float:
    """Estimate the vertical space required for footnotes."""

    if not heights:
        return 0.0
    cols = min(3, len(heights))
    bounds = _column_bounds_fill(heights, cols)
    col_totals = []
    for start, end in zip(bounds[:-1], bounds[1:]):
        col_totals.append(sum(heights[start:end]))
    max_height = max(col_totals) if col_totals else 0.0
    buffer = (
        settings.footnote_rule_height
        + settings.footnote_extra_buffer
        + settings.column_gap / 2
    )
    return max_height + buffer


def _header_height(blocks: Sequence[Paragraph], body_width: float, gap: float) -> float:
    """Compute total vertical space for header flowables."""

    if not blocks:
        return 0.0
    height = 0.0
    prev_after = 0.0
    for idx, block in enumerate(blocks):
        space_before = 0.0 if idx == 0 else block.getSpaceBefore()
        collapse = max(prev_after, space_before) if idx > 0 else space_before
        height += collapse
        block_height = measure_height(block, body_width)
        height += block_height
        prev_after = block.getSpaceAfter()
    height += prev_after  # trailing spaceAfter of last block
    return max(0.0, height) + gap


@dataclass(slots=True)
class PageSettings:
    """Geometry constants used during layout."""

    page_width: float = letter[0] * 0.8
    page_height: float = letter[1] * 0.8
    margin_left: float = 0.65 * inch * 0.8
    margin_right: float = 0.65 * inch * 0.8
    margin_top: float = 0.75 * inch * 0.8
    margin_bottom: float = 0.75 * inch * 0.8
    column_gap: float = 12.0 * 0.8
    footnote_rule_height: float = 0.0
    header_gap: float = 6.0 * 0.8
    footnote_extra_buffer: float = 0.0
    text_extra_buffer: float = 0.0
    footnote_row_padding: float = 0.0
    footnote_chapter_width: float = 6.0 * 0.8
    footnote_verse_width: float = 12.0 * 0.8
    footnote_letter_width: float = 6.0 * 0.8
    footnote_letter_gap: float = 1 * 0.8
    font_name: str = "Palatino"
    font_bold_name: str = "Palatino-Bold"
    footnote_font_size: float = 8.0
    debug_borders: bool = False

    @property
    def body_width(self) -> float:
        return self.page_width - self.margin_left - self.margin_right

    @property
    def body_height(self) -> float:
        return self.page_height - self.margin_top - self.margin_bottom + EPSILON

    def text_column_width(self) -> float:
        return (self.body_width) / 2

    def footnote_column_width(self) -> float:
        return (self.body_width - 2 * self.column_gap) / 3

    def footnote_text_width(self) -> float:
        return (
            self.footnote_column_width()
            - self.footnote_chapter_width
            - self.footnote_verse_width
            - self.footnote_letter_width
            - self.footnote_letter_gap
        )


def register_palatino() -> str:
    """Register the Palatino system font (regular and bold) and return the regular name."""

    font_path = "/System/Library/Fonts/Palatino.ttc"
    regular = "Palatino"
    bold = "Palatino-Bold"
    italic = "Palatino-Italic"
    bold_italic = "Palatino-BoldItalic"
    if regular not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular, font_path))
    if bold not in pdfmetrics.getRegisteredFontNames():
        # Palatino.ttc face order on macOS: 0=Roman,1=Italic,2=Bold,3=BoldItalic
        pdfmetrics.registerFont(TTFont(bold, font_path, subfontIndex=2))
    if italic not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(italic, font_path, subfontIndex=1))
    if bold_italic not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_italic, font_path, subfontIndex=3))
    return regular


def register_hebrew_fallback() -> str:
    """Register a Hebrew-capable font and return its name.

    Returns:
        The font name that supports Hebrew glyphs; defaults to Palatino when no
        candidate font is present on the host system.
    """

    candidates = [
        ("/System/Library/Fonts/Supplemental/ArialHebrew.ttf", "ArialHebrew"),
        ("/System/Library/Fonts/Supplemental/ArialUnicode.ttf", "ArialUnicode"),
        ("/System/Library/Fonts/SFHebrew.ttf", "SFHebrew"),
        ("/System/Library/Fonts/SFHebrewRounded.ttf", "SFHebrewRounded"),
        ("/Library/Fonts/Arial Unicode.ttf", "ArialUnicodeFull"),
        ("/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf", "NotoSansHebrew"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans"),
    ]
    for path, name in candidates:
        if not Path(path).exists():
            continue
        if name not in pdfmetrics.getRegisteredFontNames():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                # Skip fonts that fail to load or lack TrueType data.
                continue
        return name
    return "Palatino"


def build_styles(font_name: str) -> Dict[str, ParagraphStyle]:
    """Create paragraph styles used in the document."""

    base = getSampleStyleSheet()
    italic_name = f"{font_name}-Italic"
    hebrew_font = register_hebrew_fallback()
    body = ParagraphStyle(
        "Body",
        parent=base["Normal"],
        fontName=font_name,
        fontSize=11,
        leading=13,
        alignment=TA_JUSTIFY,
        spaceAfter=0,
        spaceBefore=0,
        leftIndent=0,
        firstLineIndent=8,
    )
    # Store the italic companion font for inline superscripts.
    setattr(body, "italic_font_name", italic_name)
    body_cont = _continuation_style(body)
    header = ParagraphStyle(
        "Header",
        parent=base["Heading2"],
        fontName=font_name,
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=6,
        keepWithNext=False,
    )
    section = ParagraphStyle(
        "Section",
        parent=header,
        leading=13,
        spaceBefore=6.5,
        spaceAfter=6.5,
        fontName=font_name,
    )
    # Store the Hebrew-capable font on the style for targeted glyph wrapping.
    setattr(section, "hebrew_font_name", hebrew_font)
    chapter_heading = ParagraphStyle(
        "ChapterHeading",
        parent=base["Normal"],
        fontName=font_name,
        fontSize=11,
        leading=13,
        alignment=TA_CENTER,
        spaceBefore=0,
        spaceAfter=0,
    )
    preface = ParagraphStyle(
        "Preface",
        parent=base["Normal"],
        fontName=italic_name,
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        spaceAfter=6,
        italic=True,
    )
    study = ParagraphStyle(
        "Study",
        parent=body,
        fontName=italic_name,
        italic=True,
        spaceAfter=0,
        leftIndent=0,
        firstLineIndent=0,
        justifyLastLine=0,
    )
    study_first = ParagraphStyle(
        "StudyFirst",
        parent=study,
        justifyLastLine=1,
    )
    body_justify_last = ParagraphStyle(
        "BodyJustifyLast",
        parent=body,
        justifyLastLine=1,
    )
    body_cont_justify_last = ParagraphStyle(
        "BodyContJustifyLast",
        parent=body_cont,
        justifyLastLine=1,
    )
    footnote = ParagraphStyle(
        "Footnote",
        parent=base["Normal"],
        fontName=font_name,
        fontSize=7.8,
        leading=8.0,
        alignment=TA_LEFT,
        leftIndent=0,
        spaceAfter=0,
        spaceBefore=0,
    )
    footnote_ch = ParagraphStyle(
        "FootnoteCh",
        parent=footnote,
        fontName="Palatino-Bold",
    )
    footnote_letter = ParagraphStyle(
        "FootnoteLetter",
        parent=footnote,
        fontName=italic_name,
        italic=True,
    )
    footnote.tabs = [
        (0, TA_LEFT, 0),
        (18, TA_RIGHT, 0),
        (30, TA_LEFT, 0),
        (34, TA_LEFT, 0),
    ]
    return {
        "body": body,
        "body-cont": body_cont,
        "body-justify-last": body_justify_last,
        "body-cont-justify-last": body_cont_justify_last,
        "header": header,
        "section": section,
        "chapter_heading": chapter_heading,
        "preface": preface,
        "study": study,
        "study_first": study_first,
        "footnote": footnote,
        "footnote_ch": footnote_ch,
        "footnote_letter": footnote_letter,
    }
