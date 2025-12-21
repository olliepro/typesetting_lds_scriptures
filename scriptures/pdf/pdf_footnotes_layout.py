"""Footnote layout, placement, and rewriting helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, Iterable, List, Sequence
import html as htmllib
import re

from bs4 import BeautifulSoup
from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics

from ..layout_utils import measure_height
from ..models import Book, FootnoteEntry
from .pdf_settings import PageSettings
from .pdf_text import _collapse_space_after_sup
from .pdf_text_html import _line_fragments
from .pdf_types import FlowItem, FootnoteRow, VerseRange
from .pdf_footnotes_labels import _range_label
from ..text import hyphenate_html


@dataclass(slots=True)
class FootnoteRowText:
    """Raw footnote row text used for width calculation.

    Args:
        chapter: Chapter text value.
        verse: Verse text value.
        letter: Letter value.
        text: Footnote text HTML.
    """

    chapter: str
    verse: str
    letter: str
    text: str


@dataclass(slots=True)
class _PlacementState:
    """Intermediate placement state for footnote fitting."""

    placed: List[FootnoteEntry]
    rows: List[FootnoteRow]
    heights: List[float]
    lines: List[int]
    seen: set[tuple[str, str]]

    @classmethod
    def empty(cls, *, seen: set[tuple[str, str]]) -> "_PlacementState":
        """Return an empty placement state.

        Args:
            seen: Seed set of seen chapters.
        Returns:
            _PlacementState instance.
        """

        return cls(placed=[], rows=[], heights=[], lines=[], seen=set(seen))


@dataclass(slots=True)
class FootnoteLayoutCache:
    """Caches for footnote rewrite and layout steps.

    Attributes:
        rewrite: Cached rewritten footnote HTML keyed by input signature.
        rows: Cached rendered footnote rows keyed by layout signature.
    """

    rewrite: Dict[tuple[str, int, int, int], str] = field(default_factory=dict)
    rows: Dict[
        tuple[int, int, int, int, int, tuple[int, ...], tuple[tuple[str, str], ...]],
        tuple[List[FootnoteRow], List[float], List[int], set[tuple[str, str]]],
    ] = field(default_factory=dict)


_FOOTNOTE_CACHE = FootnoteLayoutCache()


def _cache_key_id(value: object | None) -> int:
    """Return a stable cache key for optional inputs.

    Args:
        value: Optional object to key.
    Returns:
        Integer identifier or zero when absent.
    """

    return id(value) if value is not None else 0


def _entries_cache_key(*, entries: Sequence[FootnoteEntry]) -> tuple[int, ...]:
    """Return a stable cache key for footnote entries.

    Args:
        entries: Footnote entries.
    Returns:
        Tuple of entry object ids.
    """

    return tuple(id(entry) for entry in entries)


def _seen_cache_key(
    *, seen_chapters: set[tuple[str, str]] | None
) -> tuple[tuple[str, str], ...]:
    """Return a stable cache key for seen chapter labels.

    Args:
        seen_chapters: Chapters already labeled.
    Returns:
        Sorted tuple of chapter identifiers.
    """

    return tuple(sorted(seen_chapters)) if seen_chapters else ()


def _rows_cache_key(
    *,
    entries: Sequence[FootnoteEntry],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    page_lookup: Dict[tuple[str, str], int] | None,
    code_map: Dict[str, str] | None,
    seen_chapters: set[tuple[str, str]] | None,
) -> tuple[int, int, int, int, int, tuple[int, ...], tuple[tuple[str, str], ...]]:
    """Return a cache key for footnote row rendering.

    Args:
        entries: Footnote entries.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        page_lookup: Page lookup mapping.
        code_map: Scripture code mapping.
        seen_chapters: Chapters already labeled.
    Returns:
        Tuple suitable for cache lookup.
    """

    return (
        _cache_key_id(styles),
        _cache_key_id(settings),
        _cache_key_id(hyphenator),
        _cache_key_id(page_lookup),
        _cache_key_id(code_map),
        _entries_cache_key(entries=entries),
        _seen_cache_key(seen_chapters=seen_chapters),
    )


def _rewrite_cache_key(
    *,
    html: str,
    hyphenator: Pyphen,
    page_lookup: Dict[tuple[str, str], int] | None,
    code_map: Dict[str, str] | None,
) -> tuple[str, int, int, int]:
    """Return a cache key for rewritten footnote HTML.

    Args:
        html: Footnote HTML fragment.
        hyphenator: Hyphenation helper.
        page_lookup: Page lookup mapping.
        code_map: Scripture code mapping.
    Returns:
        Tuple suitable for cache lookup.
    """

    return (
        html,
        _cache_key_id(hyphenator),
        _cache_key_id(page_lookup),
        _cache_key_id(code_map),
    )


def _footnote_flowable(
    *, text: str, style: ParagraphStyle, width: float
) -> tuple[Paragraph, float]:
    """Create a Paragraph flowable for a single footnote segment.

    Args:
        text: HTML fragment for the footnote text.
        style: Paragraph style to apply.
        width: Column width for measuring height.
    Returns:
        Tuple of (Paragraph, measured height).
    """

    para = Paragraph(text, style)
    return para, measure_height(flowable=para, width=width)


def _footnote_column_widths(
    *,
    rows: Sequence[FootnoteRowText],
    include_chapter: bool,
    settings: PageSettings,
) -> tuple[float, float, float, float]:
    """Compute dynamic footnote column widths based on content.

    Args:
        rows: Raw footnote rows.
        include_chapter: Whether chapter column is included.
        settings: Page settings.
    Returns:
        Tuple of (chapter, verse, letter, text) widths.
    """

    font = settings.font_name
    font_ch = settings.font_bold_name or settings.font_name
    size = settings.footnote_font_size
    min_w = 6.0
    max_vs = _max_cell_width(
        values=(row.verse for row in rows), font_name=font, size=size
    )
    max_lt = _max_cell_width(
        values=(row.letter for row in rows), font_name=font, size=size
    )
    if include_chapter:
        max_ch = _max_cell_width(
            values=(row.chapter for row in rows), font_name=font_ch, size=size
        )
        ch_w = max(min_w, max_ch + 1.0)
    else:
        ch_w = 0.0
    vs_w = max(min_w, max_vs + 1.0)
    lt_w = max(min_w, max_lt + settings.footnote_letter_gap)
    txt_w = max(24.0, settings.footnote_column_width() - (ch_w + vs_w + lt_w))
    return ch_w, vs_w, lt_w, txt_w


def _max_cell_width(
    *, values: Iterable[str], font_name: str, size: float
) -> float:
    """Return the maximum string width for a set of values.

    Args:
        values: Iterable of string values.
        font_name: Font name to measure with.
        size: Font size in points.
    Returns:
        Maximum width in points.
    """

    widths = [pdfmetrics.stringWidth(_plain_cell(val), font_name, size) for val in values]
    return max(widths, default=0.0)


@lru_cache(maxsize=4096)
def _strip_html_tags(*, html_text: str) -> str:
    """Return plain text from a small HTML fragment.

    Args:
        html_text: HTML fragment to sanitize.
    Returns:
        Plain text with entities unescaped.

    Example:
        >>> _strip_html_tags(html_text="<a>Ref</a>")
        'Ref'
    """

    text = re.sub(r"<[^>]+>", "", html_text)
    text = htmllib.unescape(text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _plain_cell(value: object) -> str:
    """Return plain text for a footnote table cell.

    Args:
        value: Cell value.
    Returns:
        Plain text string.
    """

    get_plain_text = getattr(value, "getPlainText", None)
    if callable(get_plain_text):
        return str(get_plain_text())
    if isinstance(value, Paragraph):
        return value.getPlainText()
    if isinstance(value, str):
        if "<" in value:
            return _strip_html_tags(html_text=value)
        return value
    return str(value) if value else ""


def _footnote_rows(
    *,
    entries: Sequence[FootnoteEntry],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    page_lookup: Dict[tuple[str, str], int] | None = None,
    code_map: Dict[str, str] | None = None,
    seen_chapters: set[tuple[str, str]] | None = None,
) -> tuple[List[FootnoteRow], List[float], List[int], set[tuple[str, str]]]:
    """Create footnote table rows and their heights.

    Args:
        entries: Footnote entries to include.
        styles: Paragraph styles for footnotes.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        page_lookup: Optional mapping for page references.
        code_map: Optional map of scripture codes to slugs.
        seen_chapters: Chapters already labeled.
    Returns:
        Tuple of (rows, heights, line_counts, seen_chapters).
    """

    cache_key = _rows_cache_key(
        entries=entries,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        page_lookup=page_lookup,
        code_map=code_map,
        seen_chapters=seen_chapters,
    )
    cached = _FOOTNOTE_CACHE.rows.get(cache_key)
    if cached is not None:
        return cached
    rows_raw, updated_seen = _footnote_raw_rows(
        entries=entries,
        hyphenator=hyphenator,
        page_lookup=page_lookup,
        code_map=code_map,
        seen_chapters=seen_chapters,
    )
    include_chapter = any(row.chapter for row in rows_raw)
    widths = _footnote_column_widths(
        rows=rows_raw,
        include_chapter=include_chapter,
        settings=settings,
    )
    rows_raw = _split_rows_for_column_wrap(
        rows_raw=rows_raw,
        styles=styles,
        txt_width=widths[3],
    )
    rows, heights, line_counts = _footnote_render_rows(
        rows_raw=rows_raw,
        styles=styles,
        widths=widths,
        settings=settings,
    )
    result = (rows, heights, line_counts, updated_seen)
    _FOOTNOTE_CACHE.rows[cache_key] = result
    return result


def _footnote_raw_rows(
    *,
    entries: Sequence[FootnoteEntry],
    hyphenator: Pyphen,
    page_lookup: Dict[tuple[str, str], int] | None,
    code_map: Dict[str, str] | None,
    seen_chapters: set[tuple[str, str]] | None,
) -> tuple[List[FootnoteRowText], set[tuple[str, str]]]:
    """Return raw footnote rows and updated seen chapters.

    Args:
        entries: Footnote entries to include.
        hyphenator: Hyphenation helper.
        page_lookup: Optional page lookup map.
        code_map: Optional scripture code map.
        seen_chapters: Chapters already labeled.
    Returns:
        Tuple of (raw rows, updated seen chapters).
    """

    rows_raw: List[FootnoteRowText] = []
    seen_chapters = set(seen_chapters) if seen_chapters else set()
    last_key: tuple[str, str, str] | None = None
    for entry in entries:
        ch_key = (entry.book_slug, entry.chapter)
        ch_raw = entry.chapter if ch_key not in seen_chapters else ""
        vs = (
            entry.verse
            if (entry.book_slug, entry.chapter, entry.verse) != last_key
            else ""
        )
        segments = _entry_segments(
            entry=entry,
            hyphenator=hyphenator,
            page_lookup=page_lookup,
            code_map=code_map,
        )
        for seg_idx, seg in enumerate(segments):
            rows_raw.append(
                FootnoteRowText(
                    chapter=ch_raw if seg_idx == 0 else "",
                    verse=vs if seg_idx == 0 else "",
                    letter=entry.letter if seg_idx == 0 else "",
                    text=seg,
                )
            )
        seen_chapters.add(ch_key)
        last_key = (entry.book_slug, entry.chapter, entry.verse)
    return rows_raw, seen_chapters


def _entry_segments(
    *,
    entry: FootnoteEntry,
    hyphenator: Pyphen,
    page_lookup: Dict[tuple[str, str], int] | None,
    code_map: Dict[str, str] | None,
) -> List[str]:
    """Return rewritten, hyphenated segments for a footnote entry.

    Args:
        entry: Footnote entry.
        hyphenator: Hyphenation helper.
        page_lookup: Optional page lookup map.
        code_map: Optional scripture code map.
    Returns:
        List of HTML segments.
    """

    base_segments = entry.segments if entry.segments else [entry.text]
    segments: List[str] = []
    for seg in base_segments:
        rewritten = _rewrite_entry_text(
            html=seg,
            hyphenator=hyphenator,
            page_lookup=page_lookup,
            code_map=code_map,
        )
        if rewritten:
            segments.append(rewritten)
    return segments or [""]


def _footnote_render_rows(
    *,
    rows_raw: Sequence[FootnoteRowText],
    styles: Dict[str, ParagraphStyle],
    widths: tuple[float, float, float, float],
    settings: PageSettings,
) -> tuple[List[FootnoteRow], List[float], List[int]]:
    """Render footnote rows into Paragraph cells with heights.

    Args:
        rows_raw: Raw footnote row text.
        styles: Paragraph styles.
        widths: Column widths.
        settings: Page settings.
    Returns:
        Tuple of (rows, heights, line_counts).
    """

    _, _, _, txt_w = widths
    rows: List[FootnoteRow] = []
    heights: List[float] = []
    line_counts: List[int] = []
    for row in rows_raw:
        flow, flow_height = _footnote_flowable(
            text=row.text, style=styles["footnote"], width=txt_w
        )
        height = flow_height + 2 * settings.footnote_row_padding
        ch_cell = Paragraph(row.chapter, styles["footnote_ch"]) if row.chapter else ""
        letter_cell = (
            Paragraph(row.letter, styles["footnote_letter"]) if row.letter else ""
        )
        rows.append(
            FootnoteRow(
                chapter=ch_cell,
                verse=row.verse,
                letter=letter_cell,
                text=flow,
            )
        )
        heights.append(height)
        line_counts.append(_flow_line_count(flow=flow, width=txt_w))
    return rows, heights, line_counts


def _split_rows_for_column_wrap(
    *,
    rows_raw: Sequence[FootnoteRowText],
    styles: Dict[str, ParagraphStyle],
    txt_width: float,
) -> List[FootnoteRowText]:
    """Split long footnote rows into line-sized segments for column wrapping.

    Args:
        rows_raw: Raw footnote rows to split.
        styles: Paragraph styles for footnotes.
        txt_width: Text column width for wrapping.
    Returns:
        List of FootnoteRowText rows with long entries split into lines.

    Example:
        >>> rows = [FootnoteRowText(chapter="1", verse="1", letter="a", text="Line one Line two")]
        >>> split = _split_rows_for_column_wrap(rows_raw=rows, styles={"footnote": ParagraphStyle("Footnote")}, txt_width=40)
        >>> len(split) >= 1
        True
    """

    if not rows_raw:
        return []
    split_rows: List[FootnoteRowText] = []
    style = styles["footnote"]
    for row in rows_raw:
        if not row.text:
            split_rows.append(row)
            continue
        para = Paragraph(row.text, style)
        line_htmls = _line_fragments(para=para, width=txt_width)
        if len(line_htmls) <= 1:
            split_rows.append(row)
            continue
        for idx, line_html in enumerate(line_htmls):
            split_rows.append(
                FootnoteRowText(
                    chapter=row.chapter if idx == 0 else "",
                    verse=row.verse if idx == 0 else "",
                    letter=row.letter if idx == 0 else "",
                    text=line_html,
                )
            )
    return split_rows


def _flow_line_count(*, flow: Paragraph, width: float) -> int:
    """Return the wrapped line count for a Paragraph.

    Args:
        flow: Paragraph flowable.
        width: Column width for wrapping.
    Returns:
        Number of wrapped lines.
    """

    flow.wrap(width, 10_000)
    bl_para = getattr(flow, "blPara", None)
    lines = getattr(bl_para, "lines", None) if bl_para is not None else None
    if lines is not None:
        return len(lines)
    return 1


def _rewrite_entry_text(
    *,
    html: str,
    hyphenator: Pyphen,
    page_lookup: Dict[tuple[str, str], int] | None,
    code_map: Dict[str, str] | None,
) -> str:
    """Return cached rewritten footnote HTML.

    Args:
        html: Raw footnote HTML.
        hyphenator: Hyphenation helper.
        page_lookup: Optional page lookup map.
        code_map: Optional scripture code map.
    Returns:
        Rewritten HTML string.
    """

    cache_key = _rewrite_cache_key(
        html=html,
        hyphenator=hyphenator,
        page_lookup=page_lookup,
        code_map=code_map,
    )
    cached = _FOOTNOTE_CACHE.rewrite.get(cache_key)
    if cached is not None:
        return cached
    rewritten = _rewrite_entry_text_uncached(
        html=html,
        hyphenator=hyphenator,
        page_lookup=page_lookup,
        code_map=code_map,
    )
    _FOOTNOTE_CACHE.rewrite[cache_key] = rewritten
    return rewritten


def _rewrite_entry_text_uncached(
    *,
    html: str,
    hyphenator: Pyphen,
    page_lookup: Dict[tuple[str, str], int] | None,
    code_map: Dict[str, str] | None,
) -> str:
    """Convert entry HTML into hyphenated text with adjusted links.

    Args:
        html: Raw footnote HTML.
        hyphenator: Hyphenation helper.
        page_lookup: Optional page lookup map.
        code_map: Optional scripture code map.
    Returns:
        Rewritten HTML string.
    """

    html_out = html
    if page_lookup and code_map and "<a" in html:
        soup = BeautifulSoup(html, "html.parser")
        _update_anchor_links(soup=soup, page_lookup=page_lookup, code_map=code_map)
        html_out = soup.decode_contents()
    html_out = _normalize_entry_html(html_out=html_out)
    return hyphenate_html(html_out, hyphenator)


def _update_anchor_links(
    *,
    soup: BeautifulSoup,
    page_lookup: Dict[tuple[str, str], int],
    code_map: Dict[str, str],
) -> None:
    """Update anchor hrefs to page references when possible.

    Args:
        soup: BeautifulSoup object to update.
        page_lookup: Mapping of (book_slug, chapter) to page number.
        code_map: Mapping of church URI codes to book slugs.
    Returns:
        None.
    """

    for anchor in soup.find_all("a", href=True):
        target = _extract_book_chapter(href=anchor["href"])
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


def _extract_book_chapter(*, href: str) -> tuple[str, str] | None:
    """Pull (book_code, chapter) from a scripture href.

    Args:
        href: Anchor href to parse.
    Returns:
        Tuple of (book_code, chapter) or None when parsing fails.
    """

    parts = [p for p in href.split("/") if p]
    if "scriptures" not in parts:
        return None
    idx = parts.index("scriptures")
    if idx + 2 >= len(parts):
        return None
    book_code = parts[idx + 2]
    chapter_part = parts[idx + 3] if len(parts) > idx + 3 else ""
    chapter = chapter_part.split("?")[0]
    return book_code, chapter


def _normalize_entry_html(*, html_out: str) -> str:
    """Normalize HTML for footnote rendering.

    Args:
        html_out: Raw HTML string.
    Returns:
        Normalized HTML string.
    """

    html_out = htmllib.unescape(html_out)
    html_out = html_out.replace("\u00a0", " ")
    html_out = _collapse_space_after_sup(html_out)
    html_out = re.sub(r"([A-Za-z])<a\b", r"\1 <a", html_out)
    html_out = re.sub(r"\.\s*<a\b", ". <a", html_out)
    html_out = re.sub(r"\b(TG|HEB)\s*(?=[A-Za-z])", r"\1 ", html_out)
    html_out = re.sub(r"\s{2,}", " ", html_out)
    return html_out


def _footnote_height(*, heights: Sequence[float], settings: PageSettings) -> float:
    """Estimate the vertical space required for footnotes.

    Args:
        heights: Row heights.
        settings: Page settings.
    Returns:
        Total height required for the footnote block.
    """

    if not heights:
        return 0.0
    cols = min(3, len(heights))
    from .pdf_columns import _column_bounds_fill

    bounds = _column_bounds_fill(weights=heights, columns=cols)
    col_totals = [sum(heights[start:end]) for start, end in zip(bounds[:-1], bounds[1:])]
    max_height = max(col_totals) if col_totals else 0.0
    buffer = (
        settings.footnote_rule_height
        + settings.footnote_extra_buffer
        + settings.column_gap / 2
    )
    return max_height + buffer


def _place_footnotes(
    *,
    pending: Sequence[FootnoteEntry],
    new_entries: Sequence[FootnoteEntry],
    available_height: float,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    seen_chapters: set[tuple[str, str]],
) -> tuple[
    List[FootnoteEntry],
    List[FootnoteEntry],
    List[FootnoteRow],
    List[float],
    List[int],
    float,
    set[tuple[str, str]],
]:
    """Add footnotes until height is exhausted.

    Args:
        pending: Footnotes waiting from previous pages.
        new_entries: Footnotes introduced by items on the current page.
        available_height: Space allowed for all footnotes on the page.
        styles: Paragraph styles used to render footnotes.
        hyphenator: Hyphenation helper for text.
        settings: Page geometry and spacing settings.
        seen_chapters: Chapters already labeled.
    Returns:
        placed entries, deferred entries, table rows, row heights, line counts,
        resulting footnote height, and updated set of chapters labeled.
    """

    entries = list(pending) + list(new_entries)
    seed_seen = set(seen_chapters)
    state = _PlacementState.empty(seen=seed_seen)
    for idx, entry in enumerate(entries):
        candidate = _placement_candidate(
            placed=state.placed + [entry],
            styles=styles,
            hyphenator=hyphenator,
            settings=settings,
            seed_seen=seed_seen,
        )
        if _footnote_height(heights=candidate.heights, settings=settings) <= available_height:
            state = candidate
            continue
        return _placement_result(
            state=state,
            pending=entries[idx:],
            settings=settings,
        )
    return _placement_result(state=state, pending=[], settings=settings)


def _placement_candidate(
    *,
    placed: List[FootnoteEntry],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
    seed_seen: set[tuple[str, str]],
) -> _PlacementState:
    """Return a placement state after rendering candidate entries.

    Args:
        placed: Footnotes to render.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
        seed_seen: Chapters already labeled.
    Returns:
        _PlacementState describing the rendered candidate.
    """

    rows, heights, lines, seen = _footnote_rows(
        entries=placed,
        styles=styles,
        hyphenator=hyphenator,
        settings=settings,
        seen_chapters=seed_seen,
    )
    return _PlacementState(
        placed=placed,
        rows=rows,
        heights=heights,
        lines=lines,
        seen=seen,
    )


def _placement_result(
    *, state: _PlacementState, pending: List[FootnoteEntry], settings: PageSettings
) -> tuple[
    List[FootnoteEntry],
    List[FootnoteEntry],
    List[FootnoteRow],
    List[float],
    List[int],
    float,
    set[tuple[str, str]],
]:
    """Return the final placement tuple.

    Args:
        state: Placement state.
        pending: Pending footnotes.
        settings: Page settings.
    Returns:
        Placement tuple matching _place_footnotes output.
    """

    return (
        state.placed,
        pending,
        state.rows,
        state.heights,
        state.lines,
        _footnote_height(heights=state.heights, settings=settings),
        state.seen,
    )


def _footnotes_for_items(*, items: Sequence[FlowItem]) -> List[FootnoteEntry]:
    """Collect footnotes from verse FlowItems.

    Args:
        items: FlowItems to scan.
    Returns:
        List of FootnoteEntry instances.
    """

    notes: List[FootnoteEntry] = []
    for item in items:
        if item.is_verse:
            notes.extend(item.footnotes)
    return notes


def _refresh_footnotes(
    *,
    page_slices: Sequence,
    chapter_pages: Dict[tuple[str, str], int],
    code_map: Dict[str, str],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    settings: PageSettings,
) -> None:
    """Rebuild footnote paragraphs now that page numbers are known.

    Args:
        page_slices: PageSlice objects to update.
        chapter_pages: Mapping of (book_slug, chapter) to page numbers.
        code_map: Mapping of scripture codes to book slugs.
        styles: Paragraph styles.
        hyphenator: Hyphenation helper.
        settings: Page settings.
    Returns:
        None.
    """

    for slice_ in page_slices:
        seed_seen = getattr(slice_, "seen_chapters_in", None)
        rows, heights, lines, _ = _footnote_rows(
            entries=slice_.footnote_entries,
            styles=styles,
            hyphenator=hyphenator,
            settings=settings,
            page_lookup=chapter_pages,
            code_map=code_map,
            seen_chapters=seed_seen,
        )
        slice_.footnote_rows = rows
        slice_.footnote_row_heights = heights
        slice_.footnote_row_lines = lines
        slice_.footnote_height = _footnote_height(heights=heights, settings=settings)


def _code_map_from_metadata(*, metadata: Dict | None) -> Dict[str, str]:
    """Map short church URI codes to book slugs.

    Args:
        metadata: Metadata payload from the scraper.
    Returns:
        Mapping of URI codes to book slugs.
    """

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

