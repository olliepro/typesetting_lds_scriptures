"""Footnote table rendering helpers."""

from __future__ import annotations

from typing import List, Sequence

from reportlab.lib import colors
from reportlab.platypus import Spacer, Table
from reportlab.platypus.flowables import Flowable
from reportlab.platypus.tables import TableStyle

from .pdf_columns import _column_bounds_fill
from .pdf_footnotes_layout import FootnoteRowText, _footnote_column_widths, _plain_cell
from .pdf_settings import PageSettings
from .pdf_types import FootnoteRow


class FootnoteBlock(Flowable):
    """Wrap a footnote table and draw column separator lines the full height."""

    def __init__(
        self,
        *,
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

    def wrap(self, aW: float, aH: float) -> tuple[float, float]:
        """Delegate wrap to the inner table and capture its size.

        Args:
            aW: Available width.
            aH: Available height.
        Returns:
            Tuple of (width, height).
        """

        self.width, self.height = self.table.wrap(aW, aH)
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


def _footnote_table(
    *,
    rows: Sequence[FootnoteRow],
    row_heights: Sequence[float],
    row_lines: Sequence[int],
    settings: PageSettings,
) -> Flowable:
    """Render footnotes as a tight three-column table.

    Args:
        rows: Footnote row cells.
        row_heights: Row heights aligned with rows.
        row_lines: Line counts aligned with rows.
        settings: Page settings.
    Returns:
        Flowable to render the footnote block.
    """

    if not rows:
        return Spacer(1, 0)
    include_chapter = any(bool(row.chapter) for row in rows)
    raw_rows = [
        FootnoteRowText(
            chapter=_plain_cell(row.chapter),
            verse=_plain_cell(row.verse),
            letter=_plain_cell(row.letter),
            text=row.text.getPlainText(),
        )
        for row in rows
    ]
    col_widths_dynamic = _footnote_column_widths(
        rows=raw_rows,
        include_chapter=include_chapter,
        settings=settings,
    )
    bounds = _column_bounds_fill(weights=row_lines, columns=3)
    column_tables = _footnote_column_tables(
        rows=rows,
        row_heights=row_heights,
        bounds=bounds,
        include_chapter=include_chapter,
        settings=settings,
        col_widths_dynamic=col_widths_dynamic,
    )
    return _footnote_outer_table(
        column_tables=column_tables,
        settings=settings,
    )


def _footnote_column_tables(
    *,
    rows: Sequence[FootnoteRow],
    row_heights: Sequence[float],
    bounds: Sequence[int],
    include_chapter: bool,
    settings: PageSettings,
    col_widths_dynamic: tuple[float, float, float, float],
) -> List[Flowable]:
    """Build inner tables for each footnote column.

    Args:
        rows: Footnote row cells.
        row_heights: Row heights aligned with rows.
        bounds: Column boundaries.
        include_chapter: Whether chapter column is included.
        settings: Page settings.
        col_widths_dynamic: Computed widths for cells.
    Returns:
        List of column tables.
    """

    column_tables: List[Flowable] = []
    for start, end in zip(bounds[:-1], bounds[1:]):
        segment = rows[start:end]
        seg_heights = row_heights[start:end]
        column_tables.append(
            _footnote_column_table(
                segment=segment,
                seg_heights=seg_heights,
                include_chapter=include_chapter,
                settings=settings,
                col_widths_dynamic=col_widths_dynamic,
            )
        )
    return column_tables


def _footnote_column_table(
    *,
    segment: Sequence[FootnoteRow],
    seg_heights: Sequence[float],
    include_chapter: bool,
    settings: PageSettings,
    col_widths_dynamic: tuple[float, float, float, float],
) -> Flowable:
    """Build a single footnote column table.

    Args:
        segment: Rows for the column.
        seg_heights: Heights for the rows.
        include_chapter: Whether chapter column is included.
        settings: Page settings.
        col_widths_dynamic: Computed widths for cells.
    Returns:
        Table or Spacer for the column.
    """

    if not segment:
        return Spacer(1, 0)
    data = [row.cells(include_chapter=include_chapter) for row in segment]
    inner_widths = _inner_col_widths(
        include_chapter=include_chapter,
        col_widths_dynamic=col_widths_dynamic,
    )
    table = Table(
        data,
        colWidths=inner_widths,
        rowHeights=seg_heights,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            _footnote_inner_styles(
                include_chapter=include_chapter,
                settings=settings,
            )
        )
    )
    return table


def _inner_col_widths(
    *, include_chapter: bool, col_widths_dynamic: tuple[float, float, float, float]
) -> Sequence[float]:
    """Return inner column widths for footnote tables.

    Args:
        include_chapter: Whether chapter column is included.
        col_widths_dynamic: Computed widths for cells.
    Returns:
        Sequence of widths for table columns.
    """

    return col_widths_dynamic if include_chapter else col_widths_dynamic[1:]


def _footnote_inner_styles(
    *, include_chapter: bool, settings: PageSettings
) -> List[tuple]:
    """Return TableStyle entries for inner footnote tables.

    Args:
        include_chapter: Whether chapter column is included.
        settings: Page settings.
    Returns:
        List of TableStyle tuples.
    """

    styles = _base_inner_styles(settings=settings)
    if include_chapter:
        styles.extend(_chapter_inner_styles(settings=settings))
    else:
        styles.extend(_no_chapter_inner_styles(settings=settings))
    return styles


def _base_inner_styles(*, settings: PageSettings) -> List[tuple]:
    """Return shared inner table styles.

    Args:
        settings: Page settings.
    Returns:
        List of TableStyle tuples.
    """

    return [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), settings.footnote_row_padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), settings.footnote_row_padding),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, -1), settings.font_name),
    ]


def _chapter_inner_styles(*, settings: PageSettings) -> List[tuple]:
    """Return inner styles for chapter-inclusive tables.

    Args:
        settings: Page settings.
    Returns:
        List of TableStyle tuples.
    """

    return [
        ("FONTNAME", (0, 0), (0, -1), settings.font_bold_name),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "LEFT"),
        ("RIGHTPADDING", (2, 0), (2, -1), settings.footnote_letter_gap),
    ]


def _no_chapter_inner_styles(*, settings: PageSettings) -> List[tuple]:
    """Return inner styles for tables without chapters.

    Args:
        settings: Page settings.
    Returns:
        List of TableStyle tuples.
    """

    return [
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("RIGHTPADDING", (1, 0), (1, -1), settings.footnote_letter_gap),
        ("LEFTPADDING", (0, 0), (0, -1), 10),
    ]


def _footnote_outer_table(
    *, column_tables: Sequence[Flowable], settings: PageSettings
) -> FootnoteBlock:
    """Return the outer table that wraps footnote columns.

    Args:
        column_tables: Column tables to wrap.
        settings: Page settings.
    Returns:
        FootnoteBlock flowable.
    """

    col_width = settings.footnote_column_width()
    col_widths = (
        col_width + settings.column_gap / 2,
        col_width + settings.column_gap,
        col_width + settings.column_gap / 2,
    )
    outer = Table(
        [[column_tables[0], column_tables[1], column_tables[2]]],
        colWidths=col_widths,
        hAlign="LEFT",
    )
    outer.setStyle(TableStyle(_outer_styles(settings=settings)))
    line_xs = [col_widths[0], col_widths[0] + col_widths[1]]
    return FootnoteBlock(
        table=outer,
        line_positions=line_xs,
        line_width=settings.separator_line_width,
        line_color=settings.separator_line_color,
        top_padding=settings.column_gap / 2,
    )


def _outer_styles(*, settings: PageSettings) -> List[tuple]:
    """Return TableStyle entries for the outer footnote table.

    Args:
        settings: Page settings.
    Returns:
        List of TableStyle tuples.
    """

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
    return styles
