"""
Layout math helpers for column balancing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Sequence, Tuple

from reportlab.platypus import Flowable, KeepTogether


def measure_height(flowable: Flowable, width: float) -> float:
    """Return the wrapped height for a flowable at the given width."""

    if isinstance(flowable, KeepTogether):
        content = getattr(flowable, "_content", [])
        return sum(measure_height(child, width) for child in content)
    _, height = flowable.wrap(width, 10_000)
    return height


def optimal_partition(heights: Sequence[float], columns: int) -> Tuple[float, List[int]]:
    """Find split indices that minimize the tallest column.

    Returns:
        (min_height, split_indices) where split_indices marks the start of each
        column after the first. Order of heights is preserved.
    """

    n = len(heights)
    columns = min(columns, n or 1)

    @lru_cache(maxsize=None)
    def solve(start: int, cols: int) -> tuple[float, list[int]]:
        if cols == 1:
            return sum(heights[start:]), []
        best_height = float("inf")
        best_splits: list[int] = []
        current = 0.0
        # Leave at least one item for each remaining column
        for idx in range(start, n - cols + 1):
            current += heights[idx]
            next_height, next_splits = solve(idx + 1, cols - 1)
            candidate = max(current, next_height)
            if candidate < best_height:
                best_height = candidate
                best_splits = [idx + 1] + next_splits
        return best_height, best_splits

    return solve(0, columns)


def fits_in_columns(heights: Sequence[float], columns: int, limit: float) -> bool:
    """Check if heights can be split into columns without exceeding limit."""

    min_height, _ = optimal_partition(heights, columns)
    return min_height <= limit
