"""Support helpers for pagination fitting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from reportlab.lib.styles import ParagraphStyle

from .pdf_columns import _layout_text_blocks
from .pdf_constants import DEBUG_PAGINATION
from .pdf_settings import PageSettings
from .pdf_types import FitResult, FlowItem, TextBlock


@dataclass(slots=True)
class _FitSearchState:
    """State for searching the optimal fit count."""

    count: int
    step: int
    best: FitResult | None
    last_outcome: bool | None
    iterations: int
    stop: bool = False


@dataclass(slots=True)
class LayoutCache:
    """Memoize expensive text block layouts for reuse during paging.

    Args:
        items: FlowItems to cache.
        settings: Page settings.
        styles: Paragraph styles.
    """

    items: Sequence[FlowItem]
    settings: PageSettings
    styles: Dict[str, ParagraphStyle]
    _block_cache: Dict[tuple[int, int], tuple[List[TextBlock], float]] = field(
        default_factory=dict
    )

    def blocks_for(
        self, *, start_idx: int, count: int
    ) -> tuple[List[TextBlock], float]:
        """Return block layout and height for a contiguous slice of FlowItems.

        Args:
            start_idx: Starting index into items.
            count: Number of items to include.
        Returns:
            Tuple of (blocks, total_height).
        """

        key = (start_idx, count)
        if key in self._block_cache:
            return self._block_cache[key]
        blocks, height = _layout_text_blocks(
            items=self.items[start_idx : start_idx + count],
            settings=self.settings,
            styles=self.styles,
        )
        self._block_cache[key] = (blocks, height)
        return blocks, height


def _text_height_with_padding(
    *, height: float, has_footnotes: bool, settings: PageSettings
) -> float:
    """Add bottom padding that is applied when footnotes are present.

    Args:
        height: Raw text height.
        has_footnotes: Whether footnotes exist on the page.
        settings: Page settings.
    Returns:
        Height with extra padding when needed.
    """

    return height + (settings.column_gap / 2 if has_footnotes else 0.0)


def _debug(*, msg: str) -> None:
    """Log pagination debug output when enabled.

    Args:
        msg: Message to print.
    Returns:
        None.
    """

    if DEBUG_PAGINATION:
        print(msg)


def _expected_line_count(
    *,
    items: Sequence[FlowItem],
    start_idx: int,
    stop_idx: int,
    available_text: float,
) -> int:
    """Estimate a starting line count using average measured line height.

    Args:
        items: FlowItems in the current range.
        start_idx: Start index in items.
        stop_idx: Stop index in items.
        available_text: Available text height.
    Returns:
        Estimated line count.
    """

    slice_items = items[start_idx:stop_idx]
    if not slice_items:
        return 1
    avg_height = sum(item.height for item in slice_items) / len(slice_items)
    if avg_height <= 0:
        return 1
    estimate = int((available_text / avg_height) * 1.8)
    return max(1, min(stop_idx - start_idx, estimate))


def _available_text_height(*, header_height: float, settings: PageSettings) -> float:
    """Return vertical space available for body text on the page.

    Args:
        header_height: Height consumed by headers.
        settings: Page settings.
    Returns:
        Available text height.
    """

    return max(0.0, settings.body_height - header_height - settings.text_extra_buffer)


def _increment_iterations(*, state: _FitSearchState) -> _FitSearchState:
    """Return a new state with iterations incremented.

    Args:
        state: Current fit state.
    Returns:
        Updated fit state.
    """

    return _FitSearchState(
        count=state.count,
        step=state.step,
        best=state.best,
        last_outcome=state.last_outcome,
        iterations=state.iterations + 1,
        stop=state.stop,
    )


def _best_fit(*, current: FitResult | None, candidate: FitResult) -> FitResult | None:
    """Return the better of two fit results.

    Args:
        current: Current best fit.
        candidate: New candidate fit.
    Returns:
        Best fit result.
    """

    if candidate.fits and (current is None or candidate.count > current.count):
        return candidate
    return current


def _increment_count(*, current: int, step: int, max_count: int) -> int:
    """Return the next count when growing the search.

    Args:
        current: Current count.
        step: Step size.
        max_count: Maximum allowed count.
    Returns:
        Next count value.
    """

    if current >= max_count or step == 0:
        return current
    return min(max_count, current + step)


def _decrement_count(*, current: int, step: int) -> int:
    """Return the next count when shrinking the search.

    Args:
        current: Current count.
        step: Step size.
    Returns:
        Next count value.
    """

    if current == 1 or step == 0:
        return current
    return max(1, current - step)
