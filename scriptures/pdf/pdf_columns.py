"""Column layout helpers for PDF pagination."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, Paragraph, Spacer, Table
from reportlab.platypus.tables import TableStyle

from ..layout_utils import measure_height, optimal_partition
from .pdf_settings import PageSettings
from .pdf_text import _paragraphs_from_lines
from .pdf_types import FlowItem, TextBlock, TextColumns


def _column_bounds(*, heights: Sequence[float], columns: int) -> List[int]:
    """Return start indices for each column boundary.

    Args:
        heights: Sequence of heights to partition.
        columns: Number of columns.
    Returns:
        List of boundary indices.
    """

    if not heights:
        return [0] * (columns + 1)
    _, splits = optimal_partition(heights, min(columns, len(heights)))
    bounds = [0] + splits + [len(heights)]
    return _pad_bounds(bounds=bounds, columns=columns)


def _column_bounds_by_weights(*, weights: Sequence[float], columns: int) -> List[int]:
    """Return start indices using integer weights (e.g., line counts).

    Args:
        weights: Weight per item.
        columns: Number of columns.
    Returns:
        List of boundary indices.
    """

    if not weights:
        return [0] * (columns + 1)
    _, splits = optimal_partition(weights, min(columns, len(weights)))
    bounds = [0] + splits + [len(weights)]
    return _pad_bounds(bounds=bounds, columns=columns)


def _column_bounds_fill(*, weights: Sequence[float], columns: int) -> List[int]:
    """Sequentially fill columns left-to-right based on weight totals.

    Args:
        weights: Weight per row.
        columns: Number of columns.
    Returns:
        List of boundary indices.
    """

    if not weights:
        return [0] * (columns + 1)
    total = sum(weights)
    target = max(1, -(-total // columns))
    bounds = [0]
    acc = 0
    for idx, weight in enumerate(weights, start=1):
        acc += weight
        if acc >= target and len(bounds) < columns:
            bounds.append(idx)
            acc = 0
    bounds.append(len(weights))
    return _pad_bounds(bounds=bounds, columns=columns)


def _pad_bounds(*, bounds: List[int], columns: int) -> List[int]:
    """Ensure bounds list is sized for the column count.

    Args:
        bounds: Boundary list to pad.
        columns: Number of columns.
    Returns:
        Padded boundary list.
    """

    while len(bounds) < columns + 1:
        bounds.append(bounds[-1])
    return bounds[: columns + 1]


def _layout_columns(
    *,
    items: Sequence[FlowItem],
    max_height: float,
    settings: PageSettings,
    styles: Dict[str, ParagraphStyle],
) -> Tuple[TextColumns, float, bool]:
    """Split wrapped lines into two columns with an even line count.

    Args:
        items: FlowItems to split.
        max_height: Maximum height allowed.
        settings: Page layout settings.
        styles: Style lookup for paragraphs.
    Returns:
        Tuple of (TextColumns, table_height, fits).
    """

    columns, table_height = _layout_columns_unfitted(
        items=items, settings=settings, styles=styles
    )
    fits = table_height <= max_height
    return columns, table_height, fits


def _layout_columns_unfitted(
    *,
    items: Sequence[FlowItem],
    settings: PageSettings,
    styles: Dict[str, ParagraphStyle],
) -> Tuple[TextColumns, float]:
    """Return column layout and height without performing a fit check.

    Args:
        items: FlowItems to split.
        settings: Page layout settings.
        styles: Style lookup for paragraphs.
    Returns:
        Tuple of (TextColumns, table_height).
    """

    weights = [_line_weight(item=item) for item in items]
    split_idx = _split_index_by_weight(weights=weights)
    left_paras = _strip_leading_spacers(
        flowables=_paragraphs_from_lines(lines=items[:split_idx], styles=styles)
    )
    right_paras = _strip_leading_spacers(
        flowables=_paragraphs_from_lines(lines=items[split_idx:], styles=styles)
    )
    temp_columns = TextColumns(left=left_paras, right=right_paras, height=0.0)
    table = _text_table(columns=temp_columns, settings=settings, extend_separator=False)
    _, table_height = table.wrap(settings.body_width, 10_000)
    temp_columns.height = table_height
    return temp_columns, table_height


def _strip_leading_spacers(*, flowables: Sequence[Flowable]) -> List[Flowable]:
    """Return flowables with leading empty spacers removed.

    Args:
        flowables: Column flowables in order.
    Returns:
        Flowables without any leading Spacer or blank Paragraph entries.
    """

    trimmed = list(flowables)
    while trimmed and _is_empty_lead(flowable=trimmed[0]):
        trimmed.pop(0)
    return trimmed


def _is_empty_lead(*, flowable: Flowable) -> bool:
    """Return True when a flowable is a spacer/blank paragraph.

    Args:
        flowable: Flowable to inspect.
    Returns:
        True for Spacer or whitespace-only Paragraphs.
    """

    if isinstance(flowable, Spacer):
        return True
    if not isinstance(flowable, Paragraph):
        return False
    return not flowable.getPlainText().strip()


def _layout_text_blocks(
    *,
    items: Sequence[FlowItem],
    settings: PageSettings,
    styles: Dict[str, ParagraphStyle],
) -> tuple[List[TextBlock], float]:
    """Return text blocks and total height for a slice of FlowItems.

    Args:
        items: FlowItems to split into blocks.
        settings: Page layout settings.
        styles: Style lookup for paragraphs.
    Returns:
        Tuple of (blocks, total_height).
    """

    blocks: List[TextBlock] = []
    total = 0.0
    for is_full_width, block_items in _block_groups(items=items):
        block = _build_block(
            items=block_items,
            is_full_width=is_full_width,
            settings=settings,
            styles=styles,
        )
        blocks.append(block)
        total += block.height
    total = _suppress_leading_book_title_space(blocks=blocks, total=total)
    return blocks, total


def _leading_book_title_flowable(
    *, blocks: Sequence[TextBlock]
) -> Flowable | None:
    """Return the leading book title flowable when the page starts with one.

    Args:
        blocks: Text blocks for the page slice.
    Returns:
        Leading book title flowable, or None when absent.
    """

    if not blocks:
        return None
    first_block = blocks[0]
    if first_block.kind != "full_width" or not first_block.flowables:
        return None
    flowable = first_block.flowables[0]
    if getattr(flowable, "book_title_group", False):
        return flowable
    style = getattr(flowable, "style", None)
    if style is None:
        return None
    if getattr(style, "name", "") not in {"BookTitle", "DeclarationTitle"}:
        return None
    return flowable


def _suppress_leading_book_title_space(
    *, blocks: List[TextBlock], total: float
) -> float:
    """Remove book-title spaceBefore when it starts the page.

    Args:
        blocks: Text blocks for the page slice.
        total: Total block height before adjustment.
    Returns:
        Updated total height.
    """

    if not blocks:
        return total
    first_block = blocks[0]
    flowable = _leading_book_title_flowable(blocks=blocks)
    if flowable is None:
        return total
    space_before = flowable.getSpaceBefore()
    if space_before <= 0:
        return total
    flowable.spaceBefore = 0
    first_block.height = max(0.0, first_block.height - space_before)
    return max(0.0, total - space_before)


def _block_groups(*, items: Sequence[FlowItem]) -> List[tuple[bool, List[FlowItem]]]:
    """Group consecutive FlowItems by full-width status.

    Args:
        items: FlowItems in order.
    Returns:
        List of (is_full_width, items) groups.
    """

    if not items:
        return []
    groups: List[tuple[bool, List[FlowItem]]] = []
    current: List[FlowItem] = [items[0]]
    current_full = items[0].full_width
    for item in items[1:]:
        if item.full_width == current_full:
            current.append(item)
            continue
        groups.append((current_full, current))
        current = [item]
        current_full = item.full_width
    groups.append((current_full, current))
    return groups


def _build_block(
    *,
    items: Sequence[FlowItem],
    is_full_width: bool,
    settings: PageSettings,
    styles: Dict[str, ParagraphStyle],
) -> TextBlock:
    """Build a TextBlock for the provided items.

    Args:
        items: FlowItems to render in the block.
        is_full_width: Whether the block is full width.
        settings: Page layout settings.
        styles: Style lookup for paragraphs.
    Returns:
        TextBlock describing the block layout.
    """

    if is_full_width:
        flowables = _paragraphs_from_lines(lines=items, styles=styles)
        height = _flowables_height(flowables=flowables, width=settings.body_width)
        return TextBlock(
            kind="full_width",
            columns=None,
            flowables=flowables,
            height=height,
            items=list(items),
        )
    columns, height = _layout_columns_unfitted(
        items=items, settings=settings, styles=styles
    )
    return TextBlock(
        kind="columns",
        columns=columns,
        flowables=[],
        height=height,
        items=list(items),
    )


def _flowables_height(*, flowables: Sequence[Flowable], width: float) -> float:
    """Return total height for a stack of flowables.

    Args:
        flowables: Flowables to measure.
        width: Available width for wrapping.
    Returns:
        Total height including space before/after.
    """

    total = 0.0
    for flowable in flowables:
        total += flowable.getSpaceBefore()
        total += measure_height(flowable=flowable, width=width)
        total += flowable.getSpaceAfter()
    return total


def _line_weight(*, item: FlowItem) -> int:
    """Return a line weight for a FlowItem.

    Args:
        item: FlowItem to inspect.
    Returns:
        Integer weight for column balancing.
    """

    para = item.paragraph
    logical_lines = getattr(para, "logical_lines", None)
    if logical_lines is not None:
        try:
            return max(1, int(logical_lines))
        except Exception:
            return 1
    return 1


def _split_index_by_weight(*, weights: Sequence[int]) -> int:
    """Return the split index to balance weights between columns.

    Args:
        weights: Sequence of line weights.
    Returns:
        Index at which to split the list.
    """

    total_weight = sum(weights)
    target = (total_weight + 1) // 2
    running = 0
    split_idx = 0
    for idx, weight in enumerate(weights):
        running += weight
        split_idx = idx + 1
        if running >= target:
            break
    return split_idx


def _text_table(
    *, columns: TextColumns, settings: PageSettings, extend_separator: bool = False
) -> Table:
    """Render two text columns in reading order.

    Args:
        columns: TextColumns object.
        settings: Page settings.
        extend_separator: Whether to extend the separator into footnotes.
    Returns:
        ReportLab Table containing both columns.
    """

    col_width = settings.text_column_width()
    left_flow = columns.left if columns.left else [Spacer(1, 0)]
    right_flow = columns.right if columns.right else [Spacer(1, 0)]
    bottom_padding = settings.column_gap / 2 if extend_separator else 0
    table = Table(
        [[left_flow, right_flow]],
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
                ("BOTTOMPADDING", (0, 0), (-1, -1), bottom_padding),
                ("RIGHTPADDING", (0, 0), (0, 0), settings.column_gap / 2),
                ("LEFTPADDING", (1, 0), (1, 0), settings.column_gap / 2),
                (
                    "LINEBEFORE",
                    (1, 0),
                    (1, 0),
                    settings.separator_line_width,
                    settings.separator_line_color,
                ),
            ]
            + ([
                ("BOX", (0, 0), (-1, -1), 0.4, colors.red)
            ] if settings.debug_borders else [])
        )
    )
    return table
