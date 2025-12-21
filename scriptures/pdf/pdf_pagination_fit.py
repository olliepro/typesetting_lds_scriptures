"""Pagination fitting logic for text and footnotes."""

from __future__ import annotations

from typing import Dict, List, Sequence

from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle
from .pdf_constants import DEBUG_PAGINATION, EPSILON
from .pdf_footnotes import (
    _footnote_height,
    _footnote_rows,
    _footnotes_for_items,
    _place_footnotes,
)
from .pdf_settings import PageSettings
from .pdf_pagination_fit_support import (
    _FitSearchState,
    _available_text_height,
    _best_fit,
    _decrement_count,
    _debug,
    _expected_line_count,
    LayoutCache,
    _increment_count,
    _increment_iterations,
    _text_height_with_padding,
)
from .pdf_pagination_fit_types import (
    _CandidateFit,
    _FootnoteLayout,
    _FootnotePlacement,
    _PlanState,
)
from .pdf_types import FitResult, FlowItem, PagePlan, TextBlock
from ..models import FootnoteEntry


class PageFitter:
    """Search for the max text/footnote combo, then fill remaining text space."""

    def __init__(
        self,
        *,
        items: Sequence[FlowItem],
        start_idx: int,
        stop_idx: int,
        header_height: float,
        settings: PageSettings,
        styles: Dict[str, ParagraphStyle],
        hyphenator: Pyphen,
        pending_notes: Sequence[FootnoteEntry],
        seen_chapters: set[tuple[str, str]],
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
        self.cache = LayoutCache(items=items, settings=settings, styles=styles)
        self.available_text = _available_text_height(
            header_height=header_height, settings=settings
        )
        self.max_count = stop_idx - start_idx

    def _measure_fit(self, *, count: int) -> FitResult:
        """Return combined text and footnote layout for ``count`` lines.

        Args:
            count: Number of FlowItems to include.
        Returns:
            FitResult describing the layout.
        """

        blocks, text_height_raw = self.cache.blocks_for(
            start_idx=self.start_idx, count=count
        )
        footnote = self._measure_footnotes(count=count)
        text_height, available_fn, fits = self._fit_metrics(
            text_height_raw=text_height_raw,
            footnote=footnote,
        )
        self._log_measure_fit(
            count=count,
            text_height_raw=text_height_raw,
            text_height=text_height,
            available_fn=available_fn,
            footnote=footnote,
        )
        return self._fit_result(
            count=count,
            blocks=blocks,
            text_height=text_height,
            footnote=footnote,
            fits=fits,
        )

    def _measure_footnotes(self, *, count: int) -> _FootnoteLayout:
        """Return footnote layout data for a candidate count.

        Args:
            count: Candidate item count.
        Returns:
            _FootnoteLayout with rows and height.
        """

        new_notes = _footnotes_for_items(
            items=self.items[self.start_idx : self.start_idx + count]
        )
        rows, heights, lines, seen = _footnote_rows(
            entries=self.pending_notes + new_notes,
            styles=self.styles,
            hyphenator=self.hyphenator,
            settings=self.settings,
            seen_chapters=self.seen_chapters,
        )
        height = _footnote_height(heights=heights, settings=self.settings)
        return _FootnoteLayout(
            new_notes=new_notes,
            rows=rows,
            heights=heights,
            lines=lines,
            height=height,
            seen=seen,
        )

    def _fit_metrics(
        self, *, text_height_raw: float, footnote: _FootnoteLayout
    ) -> tuple[float, float, bool]:
        """Return text height, available footnote height, and fit flag.

        Args:
            text_height_raw: Raw text height.
            footnote: Footnote layout details.
        Returns:
            Tuple of (text_height, available_fn, fits).
        """

        text_height = _text_height_with_padding(
            height=text_height_raw,
            has_footnotes=bool(footnote.rows),
            settings=self.settings,
        )
        available_fn = self._available_footnote_height(text_height=text_height)
        fits = self._fits(
            text_height=text_height,
            footnote_height=footnote.height,
            available_fn=available_fn,
        )
        return text_height, available_fn, fits

    def _measure_debug_msg(
        self,
        *,
        count: int,
        text_height_raw: float,
        text_height: float,
        available_fn: float,
        footnote: _FootnoteLayout,
    ) -> str:
        """Return a debug message for a measurement.

        Args:
            count: Candidate item count.
            text_height_raw: Raw text height.
            text_height: Text height with padding.
            available_fn: Available footnote height.
            footnote: Footnote layout details.
        Returns:
            Debug string.
        """

        return (
            "[measure] count=%d text_raw=%.2f text_pad=%.2f "
            "avail_text=%.2f avail_fn=%.2f fn_h=%.2f rows=%d new_notes=%d pending=%d"
            % (
                count,
                text_height_raw,
                text_height,
                self.available_text,
                available_fn,
                footnote.height,
                len(footnote.rows),
                len(footnote.new_notes),
                len(self.pending_notes),
            )
        )

    def _log_measure_fit(
        self,
        *,
        count: int,
        text_height_raw: float,
        text_height: float,
        available_fn: float,
        footnote: _FootnoteLayout,
    ) -> None:
        """Emit a debug line for the current measurement.

        Args:
            count: Candidate item count.
            text_height_raw: Raw text height.
            text_height: Text height with padding.
            available_fn: Available footnote height.
            footnote: Footnote layout details.
        Returns:
            None.
        """

        _debug(
            msg=self._measure_debug_msg(
                count=count,
                text_height_raw=text_height_raw,
                text_height=text_height,
                available_fn=available_fn,
                footnote=footnote,
            )
        )

    def _fit_result(
        self,
        *,
        count: int,
        blocks: List[TextBlock],
        text_height: float,
        footnote: _FootnoteLayout,
        fits: bool,
    ) -> FitResult:
        """Return a FitResult from measured components.

        Args:
            count: Candidate item count.
            blocks: Text blocks for the candidate.
            text_height: Text height with padding.
            footnote: Footnote layout details.
            fits: Whether the layout fits.
        Returns:
            FitResult instance.
        """

        return FitResult(
            count=count,
            blocks=blocks,
            text_height=text_height,
            footnotes=footnote.new_notes,
            footnote_rows=footnote.rows,
            footnote_heights=footnote.heights,
            footnote_lines=footnote.lines,
            footnote_height=footnote.height,
            seen_chapters=footnote.seen,
            fits=fits,
        )

    def _available_footnote_height(self, *, text_height: float) -> float:
        """Return footnote height available after reserving text.

        Args:
            text_height: Text block height including padding.
        Returns:
            Available footnote height.
        """

        return self.settings.body_height - self.header_height - text_height

    def _fits(
        self, *, text_height: float, footnote_height: float, available_fn: float
    ) -> bool:
        """Return True when both text and footnotes fit.

        Args:
            text_height: Text height including padding.
            footnote_height: Footnote block height.
            available_fn: Available footnote height.
        Returns:
            True when both fit.
        """

        return text_height <= self.available_text + EPSILON and footnote_height <= max(
            0.0, available_fn + EPSILON
        )

    def _balanced_fit(self) -> FitResult:
        """Find the largest line count where text and footnotes both fit."""

        state = self._initial_fit_state()
        if DEBUG_PAGINATION:
            _debug(msg=self._fit_start_message(state=state))
        while self._continue_fit(state=state):
            state = self._step_fit(state=state)
        return self._finalize_fit(state=state)

    def _initial_fit_state(self) -> _FitSearchState:
        """Return the initial fit search state.

        Returns:
            _FitSearchState instance.
        """

        start = _expected_line_count(
            items=self.items,
            start_idx=self.start_idx,
            stop_idx=self.start_idx + 100,
            available_text=self.available_text,
        )
        count = min(self.max_count, start)
        step = 8
        return _FitSearchState(
            count=count,
            step=step,
            best=None,
            last_outcome=None,
            iterations=0,
        )

    def _fit_start_message(self, *, state: _FitSearchState) -> str:
        """Return a debug message describing fit search start.

        Args:
            state: Current fit search state.
        Returns:
            Debug string.
        """

        return (
            f"[fit] start_idx={self.start_idx} stop_idx={self.stop_idx} "
            f"start_count={state.count} step={state.step} max_count={self.max_count} "
            f"avail_text={self.available_text:.1f}"
        )

    def _continue_fit(self, *, state: _FitSearchState) -> bool:
        """Return True while the fit search should continue.

        Args:
            state: Current fit search state.
        Returns:
            True if search should continue.
        """

        return not state.stop and state.iterations < 200

    def _step_fit(self, *, state: _FitSearchState) -> _FitSearchState:
        """Advance the fit search by one iteration.

        Args:
            state: Current fit search state.
        Returns:
            Updated fit search state.
        """

        state = _increment_iterations(state=state)
        fit = self._measure_fit(count=state.count)
        best = _best_fit(current=state.best, candidate=fit)
        step, stop = self._maybe_adjust_step(state=state, fit=fit, best=best)
        next_count = self._next_count(state=state, fit=fit, step=step)
        if next_count == state.count:
            stop = True
        if DEBUG_PAGINATION and state.iterations % 25 == 0:
            _debug(msg=self._fit_progress_message(fit=fit, state=state, step=step))
        return _FitSearchState(
            count=next_count,
            step=step,
            best=best,
            last_outcome=fit.fits,
            iterations=state.iterations,
            stop=stop,
        )

    def _fit_progress_message(
        self, *, fit: FitResult, state: _FitSearchState, step: int
    ) -> str:
        """Return a debug message for fit progress.

        Args:
            fit: Fit result for the current iteration.
            state: Current fit search state.
            step: Step size.
        Returns:
            Debug string.
        """

        return (
            f"[fit] iter={state.iterations} count={state.count} step={step} "
            f"fits={fit.fits} text_h={fit.text_height:.1f} fn_h={fit.footnote_height:.1f}"
        )

    def _maybe_adjust_step(
        self, *, state: _FitSearchState, fit: FitResult, best: FitResult | None
    ) -> tuple[int, bool]:
        """Return updated step and stop flag after evaluating outcome.

        Args:
            state: Current fit search state.
            fit: Fit result for the current count.
            best: Best fit found so far.
        Returns:
            Tuple of (step, stop flag).
        """

        step = state.step
        stop = False
        outcome = fit.fits
        if state.last_outcome is not None and outcome != state.last_outcome:
            step = max(1, step // 2)
            if step == 1 and best is not None:
                if DEBUG_PAGINATION:
                    _debug(msg=self._boundary_message(best=best, count=state.count))
                stop = True
        return step, stop

    def _boundary_message(self, *, best: FitResult, count: int) -> str:
        """Return a debug message for a boundary condition.

        Args:
            best: Best fit found.
            count: Current count.
        Returns:
            Debug string.
        """

        return (
            f"[fit] boundary reached at count={count} best={best.count} "
            f"text_h={best.text_height:.1f} fn_h={best.footnote_height:.1f}"
        )

    def _next_count(self, *, state: _FitSearchState, fit: FitResult, step: int) -> int:
        """Return the next count for the fit search.

        Args:
            state: Current fit search state.
            fit: Fit result for the current count.
            step: Step size.
        Returns:
            Next count value.
        """

        if fit.fits:
            return _increment_count(
                current=state.count, step=step, max_count=self.max_count
            )
        return _decrement_count(current=state.count, step=step)

    def _finalize_fit(self, *, state: _FitSearchState) -> FitResult:
        """Return the final FitResult after search or fallback.

        Args:
            state: Final fit search state.
        Returns:
            FitResult instance.
        """

        if state.best:
            if DEBUG_PAGINATION:
                _debug(
                    msg=self._best_message(best=state.best, iterations=state.iterations)
                )
            return state.best
        return self._fallback_fit(start_count=state.count)

    def _best_message(self, *, best: FitResult, iterations: int) -> str:
        """Return a debug message for the best fit.

        Args:
            best: Best fit result.
            iterations: Iteration count.
        Returns:
            Debug string.
        """

        return (
            f"[fit] best={best.count} iters={iterations} "
            f"text_h={best.text_height:.1f} fn_h={best.footnote_height:.1f}"
        )

    def _fallback_fit(self, *, start_count: int) -> FitResult:
        """Return the fallback fit by sweeping downward.

        Args:
            start_count: Starting count to sweep from.
        Returns:
            FitResult instance.
        """

        for count in range(min(start_count, self.max_count), 0, -1):
            fit = self._measure_fit(count=count)
            if fit.fits:
                if DEBUG_PAGINATION:
                    _debug(msg=self._fallback_message(count=fit.count, fit=fit))
                return fit
        final_fit = self._measure_fit(count=1)
        if DEBUG_PAGINATION:
            _debug(msg=self._fallback_message(count=1, fit=final_fit))
        return final_fit

    def _fallback_message(self, *, count: int, fit: FitResult) -> str:
        """Return a debug message for fallback results.

        Args:
            count: Count value.
            fit: Fit result.
        Returns:
            Debug string.
        """

        return (
            f"[fit] fallback found count={count} text_h={fit.text_height:.1f} "
            f"fn_h={fit.footnote_height:.1f}"
        )

    def plan(self) -> PagePlan:
        """Compute the final PagePlan for the current page window.

        Example:
            >>> fitter = PageFitter(
            ...     items=[],
            ...     start_idx=0,
            ...     stop_idx=0,
            ...     header_height=0.0,
            ...     settings=PageSettings(),
            ...     styles={},
            ...     hyphenator=Pyphen(lang="en_US"),
            ...     pending_notes=[],
            ...     seen_chapters=set(),
            ... )
            >>> isinstance(fitter.plan(), PagePlan)
            True
        """

        base = self._balanced_fit()
        state = self._place_base_notes(base=base)
        state = self._extend_with_footnotes(state=state)
        state = self._fill_text_only(state=state)
        return PagePlan(
            count=state.count,
            blocks=state.blocks,
            text_height=state.text_height,
            header_height=self.header_height,
            placed_notes=state.placed_notes,
            footnote_rows=state.footnote_rows,
            footnote_heights=state.footnote_heights,
            footnote_lines=state.footnote_lines,
            footnote_height=state.footnote_height,
            pending_notes=state.pending_notes + state.deferred_notes,
            seen_chapters=state.seen_chapters,
        )

    def _place_base_notes(self, *, base: FitResult) -> "_PlanState":
        """Place initial footnotes for the base fit.

        Args:
            base: Base FitResult.
        Returns:
            _PlanState initialized with base layout.
        """

        available_fn = max(
            0.0, self.settings.body_height - self.header_height - base.text_height
        )
        placement = self._place_footnotes_layout(
            new_entries=base.footnotes,
            available_height=available_fn,
        )
        return _PlanState(
            count=base.count,
            blocks=base.blocks,
            text_height=base.text_height,
            placed_notes=placement.placed,
            pending_notes=placement.pending,
            footnote_rows=placement.rows,
            footnote_heights=placement.heights,
            footnote_lines=placement.lines,
            footnote_height=placement.height,
            seen_chapters=placement.seen,
        )

    def _place_footnotes_layout(
        self, *, new_entries: Sequence[FootnoteEntry], available_height: float
    ) -> _FootnotePlacement:
        """Return placement details for a footnote batch.

        Args:
            new_entries: New footnotes to place.
            available_height: Available height for footnotes.
        Returns:
            _FootnotePlacement instance.
        """

        (
            placed,
            pending,
            rows,
            heights,
            lines,
            height,
            seen,
        ) = _place_footnotes(
            pending=self.pending_notes,
            new_entries=new_entries,
            available_height=available_height,
            styles=self.styles,
            hyphenator=self.hyphenator,
            settings=self.settings,
            seen_chapters=self.seen_chapters,
        )
        return _FootnotePlacement(
            placed=placed,
            pending=pending,
            rows=rows,
            heights=heights,
            lines=lines,
            height=height,
            seen=seen,
        )

    def _extend_with_footnotes(self, *, state: "_PlanState") -> "_PlanState":
        """Grow text while footnotes still fit together.

        Args:
            state: Current plan state.
        Returns:
            Updated plan state.
        """

        while self.start_idx + state.count < self.stop_idx:
            candidate = state.count + 1
            blocks, height_raw = self.cache.blocks_for(
                start_idx=self.start_idx, count=candidate
            )
            candidate_fit = self._try_fit_candidate(
                candidate=candidate,
                height_raw=height_raw,
                blocks=blocks,
            )
            if candidate_fit is None:
                break
            state = state.update_with_candidate(candidate=candidate_fit)
        return state

    def _try_fit_candidate(
        self, *, candidate: int, height_raw: float, blocks: List[TextBlock]
    ) -> _CandidateFit | None:
        """Return candidate layout data if the count fits.

        Args:
            candidate: Candidate item count.
            height_raw: Raw text height.
            blocks: Block layout for the candidate.
        Returns:
            _CandidateFit instance when it fits; otherwise None.
        """

        available_fn = self._candidate_available_fn(height_raw=height_raw)
        new_notes = self._candidate_new_notes(candidate=candidate)
        placement = self._place_footnotes_layout(
            new_entries=new_notes,
            available_height=available_fn,
        )
        text_height = self._candidate_text_height(
            height_raw=height_raw,
            placement=placement,
        )
        self._log_candidate_fit(
            candidate=candidate,
            text_height_raw=height_raw,
            text_height=text_height,
            available_fn=available_fn,
            placement=placement,
        )
        if placement.pending or text_height > self.available_text + EPSILON:
            return None
        return self._candidate_fit(
            candidate=candidate,
            blocks=blocks,
            text_height=text_height,
            placement=placement,
        )

    def _candidate_new_notes(self, *, candidate: int) -> List[FootnoteEntry]:
        """Return new footnotes introduced by a candidate count.

        Args:
            candidate: Candidate item count.
        Returns:
            List of new FootnoteEntry objects.
        """

        new_items = self.items[self.start_idx : self.start_idx + candidate]
        return _footnotes_for_items(items=new_items)

    def _candidate_debug_msg(
        self,
        *,
        candidate: int,
        text_height_raw: float,
        text_height: float,
        available_fn: float,
        placement: _FootnotePlacement,
    ) -> str:
        """Return a debug message for candidate fit checks.

        Args:
            candidate: Candidate item count.
            text_height_raw: Raw text height.
            text_height: Text height with padding.
            available_fn: Available footnote height.
            placement: Footnote placement details.
        Returns:
            Debug string.
        """

        return (
            "[step1] cand=%d text_raw=%.2f text_pad=%.2f avail_text=%.2f "
            "avail_fn=%.2f fn_h=%.2f rows=%d pending_try=%d avail_fn_guess=%.2f"
            % (
                candidate,
                text_height_raw,
                text_height,
                self.available_text,
                available_fn,
                placement.height,
                len(placement.rows),
                len(placement.pending),
                available_fn,
            )
        )

    def _candidate_fit(
        self,
        *,
        candidate: int,
        blocks: List[TextBlock],
        text_height: float,
        placement: _FootnotePlacement,
    ) -> _CandidateFit:
        """Return a CandidateFit from placement data.

        Args:
            candidate: Candidate item count.
            blocks: Block layout for the candidate.
            text_height: Text height with padding.
            placement: Footnote placement details.
        Returns:
            _CandidateFit instance.
        """

        return _CandidateFit(
            count=candidate,
            blocks=blocks,
            text_height=text_height,
            placed_notes=placement.placed,
            pending_notes=placement.pending,
            footnote_rows=placement.rows,
            footnote_heights=placement.heights,
            footnote_lines=placement.lines,
            footnote_height=placement.height,
            seen_chapters=placement.seen,
        )

    def _candidate_available_fn(self, *, height_raw: float) -> float:
        """Return available footnote height for a candidate text height.

        Args:
            height_raw: Raw text height.
        Returns:
            Available footnote height.
        """

        height_guess = _text_height_with_padding(
            height=height_raw, has_footnotes=True, settings=self.settings
        )
        return self._available_footnote_height(text_height=height_guess)

    def _candidate_text_height(
        self, *, height_raw: float, placement: "_FootnotePlacement"
    ) -> float:
        """Return text height including padding for a candidate placement.

        Args:
            height_raw: Raw text height.
            placement: Footnote placement details.
        Returns:
            Text height with padding applied.
        """

        return _text_height_with_padding(
            height=height_raw,
            has_footnotes=bool(placement.rows),
            settings=self.settings,
        )

    def _log_candidate_fit(
        self,
        *,
        candidate: int,
        text_height_raw: float,
        text_height: float,
        available_fn: float,
        placement: _FootnotePlacement,
    ) -> None:
        """Emit a debug line for candidate fit evaluation.

        Args:
            candidate: Candidate item count.
            text_height_raw: Raw text height.
            text_height: Text height with padding.
            available_fn: Available footnote height.
            placement: Footnote placement details.
        Returns:
            None.
        """

        _debug(
            msg=self._candidate_debug_msg(
                candidate=candidate,
                text_height_raw=text_height_raw,
                text_height=text_height,
                available_fn=available_fn,
                placement=placement,
            )
        )

    def _fill_text_only(self, *, state: "_PlanState") -> "_PlanState":
        """Fill remaining space with text-only, deferring footnotes.

        Args:
            state: Current plan state.
        Returns:
            Updated plan state.
        """

        body_limit = self.settings.body_height - self.header_height
        while self.start_idx + state.count < self.stop_idx:
            candidate = state.count + 1
            blocks, height_raw = self.cache.blocks_for(
                start_idx=self.start_idx, count=candidate
            )
            height = _text_height_with_padding(
                height=height_raw,
                has_footnotes=bool(state.footnote_rows),
                settings=self.settings,
            )
            _debug(
                msg=(
                    "[step2] cand=%d text_raw=%.2f text_pad=%.2f fn_h=%.2f "
                    "body_limit=%.2f avail_text=%.2f"
                    % (
                        candidate,
                        height_raw,
                        height,
                        state.footnote_height,
                        body_limit,
                        self.available_text,
                    )
                )
            )
            if (
                height + state.footnote_height > body_limit + EPSILON
                or height > self.available_text + EPSILON
            ):
                break
            state = self._advance_text_only(
                state=state, candidate=candidate, blocks=blocks, height=height
            )
        return state

    def _advance_text_only(
        self,
        *,
        state: "_PlanState",
        candidate: int,
        blocks: List[TextBlock],
        height: float,
    ) -> "_PlanState":
        """Return updated state after accepting a text-only candidate.

        Args:
            state: Current plan state.
            candidate: Candidate count.
            blocks: Block layout for candidate.
            height: Updated text height.
        Returns:
            Updated plan state.
        """

        new_line_items = self.items[
            self.start_idx + state.count : self.start_idx + candidate
        ]
        deferred = _footnotes_for_items(items=new_line_items)
        return state.update_text_only(
            count=candidate,
            blocks=blocks,
            text_height=height,
            deferred_notes=deferred,
        )
