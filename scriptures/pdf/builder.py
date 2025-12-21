"""PDF generation for the scraped scripture corpus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Protocol, Sequence, cast

from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate, Paragraph
from tqdm import tqdm

from ..layout_utils import measure_height
from ..models import Book, FootnoteEntry, StandardWork
from .pdf_footnotes import (
    FootnoteRowText,
    _code_map_from_metadata,
    _footnote_column_widths as _footnote_column_widths_internal,
    _footnote_rows as _footnote_rows_internal,
    _footnote_table as _footnote_table_internal,
    _refresh_footnotes,
)
from .pdf_pagination import _chapter_page_map, paginate_book, paginate_books
from .pdf_settings import PageSettings, build_styles, register_palatino
from .pdf_story import _page_templates, _story_for_pages, _toc_flowables
from .pdf_text import _line_fragments, _paragraph_from_html, _verse_markup
from .pdf_types import FootnoteRow

__all__ = [
    "PageSettings",
    "build_pdf",
    "build_styles",
    "limit_books",
    "measure_height",
    "paginate_book",
    "paginate_books",
    "register_palatino",
    "select_books",
    "_footnote_column_widths",
    "_footnote_rows",
    "_footnote_table",
    "_line_fragments",
    "_paragraph_from_html",
    "_verse_markup",
]


@dataclass(slots=True)
class _FontSetup:
    """Font/style artifacts needed for PDF generation.

    Args:
        settings: Page settings with font fields populated.
        font_name: Registered regular font name.
        styles: Style map for paragraphs.
    """

    settings: PageSettings
    font_name: str
    styles: Dict[str, ParagraphStyle]


@dataclass(slots=True)
class _PageBundle:
    """Container for paginated content and related metadata.

    Args:
        page_slices: PageSlice objects in render order.
        chapter_pages: Mapping of (book_slug, chapter) to page numbers.
        # toc_flow: Table-of-contents flowables.
    """

    page_slices: List
    chapter_pages: Dict[tuple[str, str], int]
    # toc_flow: List


class _FootnoteSlice(Protocol):
    """Protocol for legacy footnote slices."""

    footnote_rows: Sequence[tuple[object, str, object, object] | FootnoteRow]
    footnote_row_heights: Sequence[float]
    footnote_row_lines: Sequence[int]


def build_pdf(
    *,
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
        settings: Optional ``PageSettings`` override.
        max_books: Per-standard-work cap used when ``include_books`` is not set.
        metadata: Optional JSON metadata produced by the scraper for code/footnote lookups.
        include_books: Optional list of book slugs to render. When provided, the
            selection overrides ``max_books``.
    Returns:
        None. Writes the generated PDF to ``output_path``.

    Example:
        >>> build_pdf(
        ...     corpus=[],
        ...     output_path=Path("output/sample.pdf"),
        ...     include_books=None,
        ... )  # doctest: +SKIP
    """

    font_setup = _prepare_fonts(settings=settings)
    trimmed = select_books(
        corpus=corpus,
        book_slugs=include_books,
        max_books=None if include_books else max_books,
    )
    bundle = _prepare_pages(
        corpus=trimmed,
        font_setup=font_setup,
        metadata=metadata,
    )
    doc = _build_doc(output_path=output_path, settings=font_setup.settings)
    _render_pdf(doc=doc, bundle=bundle, font_setup=font_setup)


def _prepare_fonts(*, settings: PageSettings | None) -> _FontSetup:
    """Return configured fonts/styles for PDF output.

    Args:
        settings: Optional PageSettings override.
    Returns:
        _FontSetup containing settings and styles.
    """

    resolved = settings or PageSettings()
    resolved.debug_borders = False
    font_name = register_palatino()
    resolved.font_name = font_name
    resolved.font_bold_name = "Palatino-Bold"
    styles = build_styles(font_name)
    return _FontSetup(settings=resolved, font_name=font_name, styles=styles)


def _prepare_pages(
    *, corpus: Sequence[StandardWork], font_setup: _FontSetup, metadata: Dict | None
) -> _PageBundle:
    """Paginate corpus, refresh footnotes, and build the TOC flowables.

    Args:
        corpus: Standard works to paginate.
        font_setup: Font/style setup for layout.
        metadata: Optional scraper metadata.
    Returns:
        _PageBundle with pages and TOC flowables.
    """

    page_slices = _paginate_corpus(
        corpus=corpus,
        styles=font_setup.styles,
        settings=font_setup.settings,
    )
    chapter_pages = _chapter_page_map(pages=page_slices)
    _refresh_footnotes(
        page_slices=page_slices,
        chapter_pages=chapter_pages,
        code_map=_code_map_from_metadata(metadata=metadata),
        styles=font_setup.styles,
        hyphenator=Pyphen(lang="en_US"),
        settings=font_setup.settings,
    )
    # toc_flow = _toc_flowables(
    #     corpus=corpus,
    #     chapter_pages=chapter_pages,
    #     styles=font_setup.styles,
    # )
    return _PageBundle(
        page_slices=page_slices,
        chapter_pages=chapter_pages,
        # toc_flow=toc_flow,
    )


def _render_pdf(
    *, doc: BaseDocTemplate, bundle: _PageBundle, font_setup: _FontSetup
) -> None:
    """Render the PDF using prepared page slices and templates.

    Args:
        doc: ReportLab document template.
        bundle: Prepared page bundle.
        font_setup: Font/style setup.
    Returns:
        None.
    """

    doc.addPageTemplates(
        _page_templates(
            page_slices=bundle.page_slices,
            settings=font_setup.settings,
            font_name=font_setup.font_name,
        )
    )
    story = _story_for_pages(
        page_slices=bundle.page_slices,
        # toc_flow=bundle.toc_flow,
        settings=font_setup.settings,
    )
    doc.build(story)


def _paginate_corpus(
    *,
    corpus: Sequence[StandardWork],
    styles: Dict[str, ParagraphStyle],
    settings: PageSettings,
) -> List:
    """Paginate every book in the corpus.

    Args:
        corpus: Standard works to paginate.
        styles: Paragraph styles.
        settings: Page settings.
    Returns:
        List of PageSlice objects.
    """

    page_slices: List = []
    hyphenator = Pyphen(lang="en_US")
    total_chapters = sum(len(book.chapters) for work in corpus for book in work.books)
    progress = (
        tqdm(total=total_chapters, desc="Rendering chapters", unit="chapter")
        if total_chapters
        else None
    )
    try:
        books = [book for work in corpus for book in work.books]
        if books:
            page_slices.extend(
                paginate_books(
                    books=books,
                    styles=styles,
                    hyphenator=hyphenator,
                    settings=settings,
                    progress=progress,
                )
            )
    finally:
        if progress is not None:
            progress.close()
    return page_slices


def _build_doc(*, output_path: Path, settings: PageSettings) -> BaseDocTemplate:
    """Return a BaseDocTemplate configured with page geometry.

    Args:
        output_path: Destination for the PDF.
        settings: Page settings.
    Returns:
        BaseDocTemplate instance.
    """

    return BaseDocTemplate(
        str(output_path),
        pagesize=(settings.page_width, settings.page_height),
        leftMargin=settings.margin_left,
        rightMargin=settings.margin_right,
        topMargin=settings.margin_top,
        bottomMargin=settings.margin_bottom,
    )


def _footnote_rows(
    *,
    entries: Sequence[FootnoteEntry],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    page_lookup: Dict[tuple[str, str], int] | None = None,
    code_map: Dict[str, str] | None = None,
    seen_chapters: set[tuple[str, str]] | None = None,
) -> tuple[
    List[tuple[object, str, object, object]],
    List[float],
    List[int],
    set[tuple[str, str]],
]:
    """Return tuple-style footnote rows for legacy callers.

    Args:
        entries: Footnote entries.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        page_lookup: Optional page lookup.
        code_map: Optional scripture code map.
        seen_chapters: Optional set of (book_slug, chapter) pairs already labeled.
    Returns:
        Tuple of (rows, heights, lines, seen_chapters).
    """

    rows, heights, lines, seen = _footnote_rows_internal(
        entries=entries,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        page_lookup=page_lookup,
        code_map=code_map,
        seen_chapters=seen_chapters,
    )
    return [_footnote_row_tuple(row=row) for row in rows], heights, lines, seen


def _footnote_column_widths(
    rows: Sequence[tuple[object, str, object, object] | FootnoteRow],
    include_chapter: bool,
    settings: PageSettings,
) -> tuple[float, float, float, float]:
    """Return footnote column widths for legacy callers.

    Args:
        rows: Sequence of legacy row tuples or FootnoteRow objects.
        include_chapter: Whether chapter column is included.
        settings: Page settings.
    Returns:
        Tuple of (chapter, verse, letter, text) widths.
    """

    row_texts = _row_texts_from_rows(rows=rows)
    return _footnote_column_widths_internal(
        rows=row_texts,
        include_chapter=include_chapter,
        settings=settings,
    )


def _footnote_table(slice_: _FootnoteSlice, settings: PageSettings):
    """Return a footnote table for legacy slice-like inputs.

    Args:
        slice_: Object with footnote_rows, footnote_row_heights, footnote_row_lines.
        settings: Page settings.
    Returns:
        Footnote table flowable.
    """

    rows = [_as_footnote_row(row=row) for row in slice_.footnote_rows]
    return _footnote_table_internal(
        rows=rows,
        row_heights=slice_.footnote_row_heights,
        row_lines=slice_.footnote_row_lines,
        settings=settings,
    )


def _footnote_row_tuple(*, row: FootnoteRow) -> tuple[object, str, object, object]:
    """Return the legacy tuple representation of a FootnoteRow.

    Args:
        row: FootnoteRow instance.
    Returns:
        Tuple of (chapter, verse, letter, text).
    """

    return row.chapter, row.verse, row.letter, row.text


def _row_texts_from_rows(
    *, rows: Sequence[tuple[object, str, object, object] | FootnoteRow]
) -> List[FootnoteRowText]:
    """Return FootnoteRowText entries from legacy row structures.

    Args:
        rows: Sequence of legacy row tuples or FootnoteRow objects.
    Returns:
        List of FootnoteRowText instances.
    """

    return [_row_text_from_row(row=row) for row in rows]


def _row_text_from_row(
    *, row: tuple[object, str, object, object] | FootnoteRow
) -> FootnoteRowText:
    """Return FootnoteRowText for a legacy row tuple or FootnoteRow.

    Args:
        row: FootnoteRow or legacy row tuple.
    Returns:
        FootnoteRowText instance.
    """

    if isinstance(row, FootnoteRow):
        return FootnoteRowText(
            chapter=_plain_cell(row.chapter),
            verse=_plain_cell(row.verse),
            letter=_plain_cell(row.letter),
            text=_plain_cell(row.text),
        )
    ch, vs, lt, txt = row
    return FootnoteRowText(
        chapter=_plain_cell(ch),
        verse=_plain_cell(vs),
        letter=_plain_cell(lt),
        text=_plain_cell(txt),
    )


def _as_footnote_row(
    *, row: tuple[object, str, object, object] | FootnoteRow
) -> FootnoteRow:
    """Return a FootnoteRow from a legacy tuple or existing row.

    Args:
        row: FootnoteRow or legacy row tuple.
    Returns:
        FootnoteRow instance.
    """

    if isinstance(row, FootnoteRow):
        return row
    ch, vs, lt, txt = row
    return FootnoteRow(
        chapter=cast(Paragraph | str, ch),
        verse=vs,
        letter=cast(Paragraph | str, lt),
        text=cast(Paragraph, txt),
    )


def _plain_cell(value: object) -> str:
    """Return plain text for a footnote row cell.

    Args:
        value: Cell value.
    Returns:
        Plain text string.
    """

    get_plain_text = getattr(value, "getPlainText", None)
    if callable(get_plain_text):
        return str(get_plain_text())
    return str(value) if value else ""


def select_books(
    *,
    corpus: Sequence[StandardWork],
    book_slugs: Sequence[str] | None = None,
    max_books: int | None = None,
) -> List[StandardWork]:
    """Return a new corpus containing only the requested books.

    Args:
        corpus: Source corpus built from the scraper output.
        book_slugs: Optional list of book slugs (case-insensitive) to include.
        max_books: Optional per-standard-work cap applied after filtering.
    Returns:
        List of ``StandardWork`` instances for the selected subset.

    Example:
        >>> nt = StandardWork(
        ...     name="New Testament",
        ...     slug="new-testament",
        ...     books=[
        ...         Book("new-testament", "John", "john", None, []),
        ...         Book("new-testament", "Luke", "luke", None, []),
        ...     ],
        ... )
        >>> selected = select_books(corpus=[nt], book_slugs=["john"], max_books=None)
        >>> [book.slug for book in selected[0].books]
        ['john']
    """

    requested = _normalize_book_slugs(book_slugs=book_slugs)
    trimmed, found = _filter_corpus(
        corpus=corpus,
        requested=requested,
        max_books=max_books,
    )
    _assert_found(requested=requested, found=found)
    return trimmed


def limit_books(
    *, corpus: Sequence[StandardWork], max_books: int
) -> List[StandardWork]:
    """Return a trimmed copy of the corpus limited per standard work.

    Args:
        corpus: Source corpus built from the scraper output.
        max_books: Number of books to keep from each standard work.
    Returns:
        List of ``StandardWork`` instances capped at ``max_books`` per work.

    Example:
        >>> limit_books(
        ...     corpus=[
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


def _normalize_book_slugs(*, book_slugs: Sequence[str] | None) -> set[str] | None:
    """Return a normalized set of requested book slugs.

    Args:
        book_slugs: Requested book slugs.
    Returns:
        Lowercased set of slugs or None when no filter is applied.
    """

    if not book_slugs:
        return None
    return {slug.lower() for slug in book_slugs}


def _filter_corpus(
    *,
    corpus: Sequence[StandardWork],
    requested: set[str] | None,
    max_books: int | None,
) -> tuple[List[StandardWork], set[str]]:
    """Return filtered corpus and found slugs.

    Args:
        corpus: Source corpus.
        requested: Requested slug filter.
        max_books: Max books per standard work.
    Returns:
        Tuple of (trimmed corpus, found slugs).
    """

    trimmed: List[StandardWork] = []
    found: set[str] = set()
    for work in corpus:
        books, found = _filter_work(
            work=work,
            requested=requested,
            max_books=max_books,
            found=found,
        )
        if books:
            trimmed.append(StandardWork(name=work.name, slug=work.slug, books=books))
    return trimmed, found


def _filter_work(
    *,
    work: StandardWork,
    requested: set[str] | None,
    max_books: int | None,
    found: set[str],
) -> tuple[List[Book], set[str]]:
    """Return filtered books for a standard work.

    Args:
        work: Standard work to filter.
        requested: Requested slug filter.
        max_books: Max books per standard work.
        found: Accumulator of found slugs.
    Returns:
        Tuple of (books, updated found slugs).
    """

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
    return books, found


def _assert_found(*, requested: set[str] | None, found: set[str]) -> None:
    """Assert that all requested slugs are present.

    Args:
        requested: Requested slug filter.
        found: Slugs found in the corpus.
    Returns:
        None.
    """

    if not requested:
        return
    missing = requested - found
    assert not missing, f"Unknown book slugs: {', '.join(sorted(missing))}"
