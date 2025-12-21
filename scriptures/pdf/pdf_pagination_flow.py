"""Pagination flow orchestration for books and chapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Protocol, Sequence

from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from ..layout_utils import measure_height
from ..models import Book, Chapter, FootnoteEntry
from .pdf_footnotes import _range_label
from .pdf_pagination_fit import PageFitter
from .pdf_settings import PageSettings
from .pdf_text import _line_items_for_chapter
from .pdf_types import ChapterFlow, FlowItem, PagePlan, PageSlice


class _ProgressTracker(Protocol):
    """Protocol for chapter rendering progress updates."""

    def update(self, n: int | float = 1) -> object:
        """Advance the progress tracker by ``n``."""


def _chapter_flows(
    *,
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    start_new_page: bool = True,
) -> List[ChapterFlow]:
    """Prepare ChapterFlow objects for a book.

    Args:
        book: Book to paginate.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        start_new_page: Whether the first chapter forces a new page.
    Returns:
        List of ChapterFlow objects.
    """

    flows: List[ChapterFlow] = []
    inner_width = settings.text_column_width() - settings.column_gap / 2
    for idx, chapter in enumerate(book.chapters):
        force_new_page = start_new_page and idx == 0
        flow = _chapter_flow(
            chapter=chapter,
            book=book,
            styles=styles,
            hyphenator=hyphenator,
            settings=settings,
            index=idx,
            inner_width=inner_width,
            force_new_page=force_new_page,
        )
        flows.append(flow)
    return flows


def _chapter_flow(
    *,
    chapter: Chapter,
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    index: int,
    inner_width: float,
    force_new_page: bool,
) -> ChapterFlow:
    """Return ChapterFlow for a specific chapter.

    Args:
        chapter: Chapter to render.
        book: Book containing the chapter.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        index: Chapter index in the book.
        inner_width: Column width for wrapping.
        force_new_page: Whether to force a new page before this chapter.
    Returns:
        ChapterFlow instance.
    """

    is_dc = book.standard_work == "doctrine-and-covenants"
    header: List[Paragraph] = []
    inline_preface = not is_dc and index > 0
    items = _line_items_for_chapter(
        chapter=chapter,
        book=book,
        styles=styles,
        hyphenator=hyphenator,
        column_width=inner_width,
        body_width=settings.body_width,
        inline_preface=inline_preface,
        include_chapter_heading=not is_dc,
    )
    return ChapterFlow(
        header=header,
        items=items,
        force_new_page=force_new_page,
    )


def _chapter_flows_for_books(
    *,
    books: Sequence[Book],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    start_new_page: bool = True,
) -> List[ChapterFlow]:
    """Prepare ChapterFlow objects for multiple books.

    Args:
        books: Books to paginate together.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        start_new_page: Whether the first chapter forces a new page.
    Returns:
        List of ChapterFlow objects in reading order.
    """

    flows: List[ChapterFlow] = []
    inner_width = settings.text_column_width() - settings.column_gap / 2
    first = True
    for book in books:
        for idx, chapter in enumerate(book.chapters):
            flows.append(
                _chapter_flow(
                    chapter=chapter,
                    book=book,
                    styles=styles,
                    hyphenator=hyphenator,
                    settings=settings,
                    index=idx,
                    inner_width=inner_width,
                    force_new_page=start_new_page and first and idx == 0,
                )
            )
        first = False
    return flows


def _collect_items_from_flows(
    *, flows: Sequence[ChapterFlow]
) -> tuple[List[FlowItem], Dict[int, List[Paragraph]], List[int]]:
    """Flatten chapter flows and track headers/breaks.

    Args:
        flows: ChapterFlow objects in order.
    Returns:
        Tuple of (items, header_map, breakpoints).
    """

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


def _collect_items(
    *,
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    start_new_page: bool = True,
) -> tuple[List[FlowItem], Dict[int, List[Paragraph]], List[int]]:
    """Flatten chapter flows and track headers/breaks.

    Args:
        book: Book to paginate.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        start_new_page: Whether the first chapter forces a new page.
    Returns:
        Tuple of (items, header_map, breakpoints).
    """

    flows = _chapter_flows(
        book=book,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        start_new_page=start_new_page,
    )
    return _collect_items_from_flows(flows=flows)


def _collect_items_for_books(
    *,
    books: Sequence[Book],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    start_new_page: bool = True,
) -> tuple[List[FlowItem], Dict[int, List[Paragraph]], List[int]]:
    """Flatten chapter flows for multiple books.

    Args:
        books: Books to paginate together.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        start_new_page: Whether the first chapter forces a new page.
    Returns:
        Tuple of (items, header_map, breakpoints).
    """

    flows = _chapter_flows_for_books(
        books=books,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        start_new_page=start_new_page,
    )
    return _collect_items_from_flows(flows=flows)


def _paginate_items(
    *,
    all_items: Sequence[FlowItem],
    header_map: Dict[int, List[Paragraph]],
    breakpoints: Sequence[int],
    book_lookup: Dict[str, Book],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    template_prefix: str,
    progress: _ProgressTracker | None,
    expected: set[tuple[str, str]],
) -> List[PageSlice]:
    """Paginate a prepared item stream into PageSlice objects.

    Args:
        all_items: FlowItems in render order.
        header_map: Map of index to header blocks.
        breakpoints: Indices where forced breaks occur.
        book_lookup: Lookup of book slug to Book.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        template_prefix: Prefix for PageTemplate ids.
        progress: Optional progress tracker.
        expected: Expected (book_slug, chapter) keys.
    Returns:
        List of PageSlice objects.
    """

    state = _PaginationState(
        total_items=len(all_items),
        pages=[],
        pending_notes=[],
        seen_chapters=set(),
    )
    progress_seen: set[tuple[str, str]] = set()
    while state.idx < state.total_items:
        state = _paginate_step(
            state=state,
            all_items=all_items,
            header_map=header_map,
            breakpoints=breakpoints,
            book_lookup=book_lookup,
            styles=styles,
            hyphenator=hyphenator,
            settings=settings,
            template_prefix=template_prefix,
        )
        progress_seen = _update_progress(
            progress=progress,
            seen=progress_seen,
            items=state.pages[-1].text_items,
        )
    if progress is not None:
        missing = expected - progress_seen
        if missing:
            progress.update(len(missing))
    return state.pages


def _chapter_progress_keys(*, items: Sequence[FlowItem]) -> set[tuple[str, str]]:
    """Return unique (book_slug, chapter) keys for the provided items.

    Args:
        items: FlowItems to scan.
    Returns:
        Set of (book_slug, chapter) keys.
    """

    return {(item.book_slug, item.chapter) for item in items if item.chapter}


def _update_progress(
    *,
    progress: _ProgressTracker | None,
    seen: set[tuple[str, str]],
    items: Sequence[FlowItem],
) -> set[tuple[str, str]]:
    """Update progress tracker for newly encountered chapters.

    Args:
        progress: Progress tracker to update.
        seen: Previously observed chapter keys.
        items: FlowItems from the latest page.
    Returns:
        Updated set of seen chapter keys.
    """

    if progress is None:
        return seen
    new_keys = _chapter_progress_keys(items=items) - seen
    if new_keys:
        progress.update(len(new_keys))
        seen.update(new_keys)
    return seen


def paginate_book(
    *,
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    progress: _ProgressTracker | None = None,
    start_new_page: bool = True,
) -> List[PageSlice]:
    """Paginate a single book into PageSlice objects.

    Args:
        book: Book to paginate.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        progress: Optional progress tracker for chapter completion.
        start_new_page: Whether the first chapter forces a new page.
    Returns:
        List of PageSlice objects.

    Example:
        >>> pages = paginate_book(
        ...     book=Book("work", "Book", "book", None, []),
        ...     styles={},
        ...     hyphenator=Pyphen(lang="en_US"),
        ...     settings=PageSettings(),
        ... )
        >>> isinstance(pages, list)
        True
    """

    all_items, header_map, breakpoints = _collect_items(
        book=book,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        start_new_page=start_new_page,
    )
    return _paginate_items(
        all_items=all_items,
        header_map=header_map,
        breakpoints=breakpoints,
        book_lookup={book.slug: book},
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        template_prefix=book.slug,
        progress=progress,
        expected={(book.slug, chapter.number) for chapter in book.chapters},
    )


def paginate_books(
    *,
    books: Sequence[Book],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    progress: _ProgressTracker | None = None,
    start_new_page: bool = True,
) -> List[PageSlice]:
    """Paginate multiple books into PageSlice objects.

    Args:
        books: Books to paginate together.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        progress: Optional progress tracker for chapter completion.
        start_new_page: Whether the first chapter forces a new page.
    Returns:
        List of PageSlice objects.
    """

    all_items, header_map, breakpoints = _collect_items_for_books(
        books=books,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        start_new_page=start_new_page,
    )
    book_lookup = {book.slug: book for book in books}
    expected = {
        (book.slug, chapter.number) for book in books for chapter in book.chapters
    }
    return _paginate_items(
        all_items=all_items,
        header_map=header_map,
        breakpoints=breakpoints,
        book_lookup=book_lookup,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        template_prefix="content",
        progress=progress,
        expected=expected,
    )


@dataclass(slots=True)
class _PaginationState:
    """Pagination state for building pages."""

    total_items: int
    pages: List[PageSlice]
    pending_notes: List[FootnoteEntry]
    seen_chapters: set[tuple[str, str]]
    idx: int = 0


def _paginate_step(
    *,
    state: _PaginationState,
    all_items: Sequence[FlowItem],
    header_map: Dict[int, List[Paragraph]],
    breakpoints: Sequence[int],
    book_lookup: Dict[str, Book],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    template_prefix: str,
) -> _PaginationState:
    """Return updated pagination state after one page.

    Args:
        state: Current pagination state.
        all_items: All FlowItems for the book.
        header_map: Map of index to header blocks.
        breakpoints: Indices where forced breaks occur.
        book_lookup: Lookup of book slug to Book.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        template_prefix: Prefix for PageTemplate ids.
    Returns:
        Updated _PaginationState.
    """

    header_blocks, header_height = _page_header_data(
        state=state, header_map=header_map, settings=settings
    )
    plan = _page_plan(
        state=state,
        all_items=all_items,
        header_height=header_height,
        breakpoints=breakpoints,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
    )
    page_slice = _page_slice(
        state=state,
        plan=plan,
        all_items=all_items,
        header_blocks=header_blocks,
        header_height=header_height,
        book_lookup=book_lookup,
        template_prefix=template_prefix,
    )
    state.pages.append(page_slice)
    return _next_pagination_state(state=state, plan=plan)


def _page_header_data(
    *,
    state: _PaginationState,
    header_map: Dict[int, List[Paragraph]],
    settings: PageSettings,
) -> tuple[List[Paragraph], float]:
    """Return header blocks and their computed height.

    Args:
        state: Current pagination state.
        header_map: Map of index to header blocks.
        settings: Page settings.
    Returns:
        Tuple of (header_blocks, header_height).
    """

    header_blocks = header_map.get(state.idx, [])
    header_height = _header_height(
        blocks=header_blocks,
        body_width=settings.body_width,
        gap=settings.header_gap,
    )
    return header_blocks, header_height


def _page_plan(
    *,
    state: _PaginationState,
    all_items: Sequence[FlowItem],
    header_height: float,
    breakpoints: Sequence[int],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
) -> PagePlan:
    """Return a PagePlan for the current page window.

    Args:
        state: Current pagination state.
        all_items: All FlowItems for the book.
        header_height: Computed header height.
        breakpoints: Indices where forced breaks occur.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
    Returns:
        PagePlan instance.
    """

    max_idx = _next_break_index(
        current=state.idx, breakpoints=breakpoints, total=state.total_items
    )
    fitter = PageFitter(
        items=all_items,
        start_idx=state.idx,
        stop_idx=max_idx,
        header_height=header_height,
        settings=settings,
        styles=styles,
        hyphenator=hyphenator,
        pending_notes=state.pending_notes,
        seen_chapters=state.seen_chapters,
    )
    return fitter.plan()


def _page_slice(
    *,
    state: _PaginationState,
    plan: PagePlan,
    all_items: Sequence[FlowItem],
    header_blocks: Sequence[Paragraph],
    header_height: float,
    book_lookup: Dict[str, Book],
    template_prefix: str,
) -> PageSlice:
    """Return a PageSlice for the current plan.

    Args:
        state: Current pagination state.
        plan: Page plan for the slice.
        all_items: All FlowItems for the book.
        header_blocks: Header flowables for the page.
        header_height: Computed header height.
        book_lookup: Lookup of book slug to Book.
        template_prefix: Prefix for PageTemplate ids.
    Returns:
        PageSlice instance.
    """

    page_items = all_items[state.idx : state.idx + plan.count]
    return PageSlice(
        text_items=page_items,
        text_blocks=plan.blocks,
        text_height=plan.text_height,
        header_height=header_height,
        footnote_rows=plan.footnote_rows,
        footnote_row_heights=plan.footnote_heights,
        footnote_row_lines=plan.footnote_lines,
        footnote_entries=plan.placed_notes,
        header_flowables=list(header_blocks),
        range_label=_range_label(items=page_items, book_lookup=book_lookup).upper(),
        template_id=f"{template_prefix}-p{len(state.pages)+1}",
        footnote_height=plan.footnote_height,
        seen_chapters_in=set(state.seen_chapters),
    )


def _next_pagination_state(
    *, state: _PaginationState, plan: PagePlan
) -> _PaginationState:
    """Return updated pagination state after applying a plan.

    Args:
        state: Current pagination state.
        plan: Page plan applied to the state.
    Returns:
        Updated _PaginationState.
    """

    return _PaginationState(
        total_items=state.total_items,
        pages=state.pages,
        pending_notes=plan.pending_notes,
        seen_chapters=plan.seen_chapters,
        idx=state.idx + plan.count,
    )


def _next_break_index(*, current: int, breakpoints: Sequence[int], total: int) -> int:
    """Return the next breakpoint index after the current one.

    Args:
        current: Current index.
        breakpoints: Sorted breakpoint indices.
        total: Total items length.
    Returns:
        Next breakpoint index (or total).
    """

    for bp in breakpoints:
        if bp > current:
            return bp
    return total


def _header_height(
    *, blocks: Sequence[Paragraph], body_width: float, gap: float
) -> float:
    """Compute total vertical space for header flowables.

    Args:
        blocks: Header paragraphs.
        body_width: Body width for measurement.
        gap: Extra gap after headers.
    Returns:
        Total header height.
    """

    if not blocks:
        return 0.0
    height = 0.0
    prev_after = 0.0
    for idx, block in enumerate(blocks):
        space_before = 0.0 if idx == 0 else block.getSpaceBefore()
        collapse = max(prev_after, space_before) if idx > 0 else space_before
        height += collapse
        height += measure_height(flowable=block, width=body_width)
        prev_after = block.getSpaceAfter()
    height += prev_after
    return max(0.0, height) + gap


def _chapter_page_map(
    *, pages: Sequence[PageSlice], toc_pages: int = 1
) -> Dict[tuple[str, str], int]:
    """Map (book_slug, chapter) to the first page number where it appears.

    Args:
        pages: Page slices in order.
        toc_pages: Number of table-of-contents pages.
    Returns:
        Mapping of (book_slug, chapter) to page number.
    """

    mapping: Dict[tuple[str, str], int] = {}
    for idx, page in enumerate(pages, start=toc_pages + 1):
        for item in page.text_items:
            if item.is_verse:
                key = (item.book_slug, item.chapter)
                mapping.setdefault(key, idx)
    return mapping
