"""Data classes for pagination fitting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..models import FootnoteEntry
from .pdf_types import FootnoteRow, TextBlock


@dataclass(slots=True)
class _FootnoteLayout:
    """Footnote layout measurements for a candidate count."""

    new_notes: List[FootnoteEntry]
    rows: List[FootnoteRow]
    heights: List[float]
    lines: List[int]
    height: float
    seen: set[tuple[str, str]]


@dataclass(slots=True)
class _FootnotePlacement:
    """Placed footnote layout with pending entries."""

    placed: List[FootnoteEntry]
    pending: List[FootnoteEntry]
    rows: List[FootnoteRow]
    heights: List[float]
    lines: List[int]
    height: float
    seen: set[tuple[str, str]]


@dataclass(slots=True)
class _CandidateFit:
    """Candidate layout data for a potential page expansion."""

    count: int
    blocks: List[TextBlock]
    text_height: float
    placed_notes: List[FootnoteEntry]
    pending_notes: List[FootnoteEntry]
    footnote_rows: List[FootnoteRow]
    footnote_heights: List[float]
    footnote_lines: List[int]
    footnote_height: float
    seen_chapters: set[tuple[str, str]]


@dataclass(slots=True)
class _PlanState:
    """Mutable state for building a PagePlan."""

    count: int
    blocks: List[TextBlock]
    text_height: float
    placed_notes: List[FootnoteEntry]
    pending_notes: List[FootnoteEntry]
    footnote_rows: List[FootnoteRow]
    footnote_heights: List[float]
    footnote_lines: List[int]
    footnote_height: float
    seen_chapters: set[tuple[str, str]]
    deferred_notes: List[FootnoteEntry] = field(default_factory=list)

    def update_with_candidate(self, *, candidate: _CandidateFit) -> "_PlanState":
        """Return a new plan state updated with a candidate fit.

        Args:
            candidate: Candidate fit data.
        Returns:
            New _PlanState instance.
        """

        return _PlanState(
            count=candidate.count,
            blocks=candidate.blocks,
            text_height=candidate.text_height,
            placed_notes=candidate.placed_notes,
            pending_notes=candidate.pending_notes,
            footnote_rows=candidate.footnote_rows,
            footnote_heights=candidate.footnote_heights,
            footnote_lines=candidate.footnote_lines,
            footnote_height=candidate.footnote_height,
            seen_chapters=candidate.seen_chapters,
            deferred_notes=self.deferred_notes,
        )

    def update_text_only(
        self,
        *,
        count: int,
        blocks: List[TextBlock],
        text_height: float,
        deferred_notes: List[FootnoteEntry],
    ) -> "_PlanState":
        """Return a new plan state after a text-only expansion.

        Args:
            count: Updated count.
            blocks: Updated text blocks.
            text_height: Updated text height.
            deferred_notes: Newly deferred footnotes.
        Returns:
            New _PlanState instance.
        """

        return _PlanState(
            count=count,
            blocks=blocks,
            text_height=text_height,
            placed_notes=self.placed_notes,
            pending_notes=self.pending_notes,
            footnote_rows=self.footnote_rows,
            footnote_heights=self.footnote_heights,
            footnote_lines=self.footnote_lines,
            footnote_height=self.footnote_height,
            seen_chapters=self.seen_chapters,
            deferred_notes=self.deferred_notes + deferred_notes,
        )
