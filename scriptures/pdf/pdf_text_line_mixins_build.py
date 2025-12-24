"""Build flow and paragraph classification mixin for line building."""

from __future__ import annotations

from typing import Dict, List, Sequence

from .pdf_text_line_base import _LineBuilderBase
from .pdf_text_line_helpers import (
    _partition_paragraphs,
    _split_before_first_verse,
    _split_intro_paragraphs,
)
from .pdf_text_line_footnotes import _footnotes_by_verse
from .pdf_types import FlowItem


class _BuildMixin(_LineBuilderBase):
    """Mixin for build flow and paragraph classification."""

    def build(self) -> List[FlowItem]:  # type: ignore[override]
        """Return FlowItems for the configured chapter.

        Returns:
            List of FlowItems for layout.
        """

        self._prepare_context()
        self.chapter_subtitles = self._collect_chapter_subtitles()
        self.book_subtitles = self._collect_book_subtitles()
        if not self.include_chapter_heading:
            for para_dict in self.chapter.paragraphs:
                self._handle_paragraph(para_dict=para_dict)
            return self.items
        if self.book.standard_work == "book-of-mormon":
            self._build_bom_with_heading_and_summary()
            return self.items
        self._build_with_heading_after_intro()
        return self.items

    def _build_with_heading_after_intro(self) -> None:
        """Insert a chapter heading after leading book intro paragraphs.

        Returns:
            None.
        """

        heading_inserted = False
        for para_dict in self.chapter.paragraphs:
            if self._should_insert_heading(para_dict=para_dict, inserted=heading_inserted):
                self._add_chapter_heading()
                heading_inserted = True
            self._handle_paragraph(para_dict=para_dict)
        if not heading_inserted:
            self._add_chapter_heading()

    def _build_bom_with_heading_and_summary(self) -> None:
        """Insert chapter heading before BOM chapter summaries.

        Returns:
            None.
        """

        intro, remainder = _split_intro_paragraphs(
            paragraphs=self.chapter.paragraphs,
            is_intro=lambda para: self._is_book_intro_paragraph(para_dict=para),
        )
        pre_verse, post_verse = _split_before_first_verse(paragraphs=remainder)
        summaries, rest_pre = _partition_paragraphs(
            paragraphs=pre_verse,
            predicate=lambda para: self._is_bom_summary_block(para_dict=para),
        )
        for para_dict in intro:
            self._handle_paragraph(para_dict=para_dict)
        if summaries:
            body_style = self.styles["body"]
            gap = body_style.leading or body_style.fontSize or 0
            self._insert_spacer(
                height=gap,
                paragraph_key=f"chapter-summary-gap-{self.para_counter}",
                full_width=self._summary_block_full_width(paragraphs=summaries),
            )
        for idx, para_dict in enumerate(summaries):
            self._handle_paragraph(para_dict=para_dict)
            if self._needs_summary_intro_gap(paragraphs=summaries, index=idx):
                body_style = self.styles["body"]
                gap = body_style.leading or body_style.fontSize or 0
                self._insert_spacer(
                    height=gap,
                    paragraph_key=f"chapter-summary-after-gap-{self.para_counter}",
                    full_width=self._summary_block_full_width(paragraphs=summaries),
                )
        self._add_chapter_heading()
        for para_dict in rest_pre:
            self._handle_paragraph(para_dict=para_dict)
        for para_dict in post_verse:
            self._handle_paragraph(para_dict=para_dict)

    def _should_insert_heading(self, *, para_dict: Dict, inserted: bool) -> bool:
        """Return True when the chapter heading should be inserted next.

        Args:
            para_dict: Paragraph payload.
            inserted: Whether the heading is already inserted.
        Returns:
            True when the heading should be inserted before this paragraph.
        """

        if inserted:
            return False
        p_type = para_dict.get("type") or ""
        if p_type in {"chapter-title", "verse"}:
            return True
        if self._is_book_intro_paragraph(para_dict=para_dict):
            return False
        if self._is_chapter_summary(para_dict=para_dict):
            return False
        if self._is_study_intro(para_dict=para_dict):
            return False
        return True

    def _is_book_intro_paragraph(self, *, para_dict: Dict) -> bool:
        """Return True when a paragraph is part of the book intro block.

        Args:
            para_dict: Paragraph payload.
        Returns:
            True for book-title/subtitle and book-summary paragraphs.
        """

        p_type = para_dict.get("type") or ""
        if p_type in {"book-title", "book-subtitle"}:
            return True
        return (para_dict.get("paragraphCategory") or "") == "book_summary"

    def _is_chapter_summary(self, *, para_dict: Dict) -> bool:
        """Return True when a paragraph is a chapter summary.

        Args:
            para_dict: Paragraph payload.
        Returns:
            True when paragraphCategory is ``chapter_summary``.
        """

        return (para_dict.get("paragraphCategory") or "") == "chapter_summary"

    def _is_jsh_section_summary(self, *, para_dict: Dict) -> bool:
        """Return True when a JSH section summary needs spacing.

        Args:
            para_dict: Paragraph payload.
        Returns:
            True for JSH section_summary paragraphs.
        """

        if self.book.slug != "joseph-smith-history":
            return False
        return (para_dict.get("paragraphCategory") or "") == "section_summary"

    def _is_jsh_historical_narrative(self, *, para_dict: Dict) -> bool:
        """Return True when a JSH paragraph is a historical narrative.

        Args:
            para_dict: Paragraph payload.
        Returns:
            True for JSH historical_narrative paragraphs.
        """

        if self.book.slug != "joseph-smith-history":
            return False
        return (para_dict.get("paragraphCategory") or "") == "historical_narrative"

    def _is_decorative_divider(self, *, para_dict: Dict) -> bool:
        """Return True when a paragraph is a decorative divider.

        Args:
            para_dict: Paragraph payload.
        Returns:
            True when paragraphCategory is ``decorative_divider``.
        """

        return (para_dict.get("paragraphCategory") or "") == "decorative_divider"

    def _is_study_intro(self, *, para_dict: Dict) -> bool:
        """Return True when a paragraph is a study intro block.

        Args:
            para_dict: Paragraph payload.
        Returns:
            True when churchId starts with ``study_intro``.
        """

        church_id = para_dict.get("churchId") or ""
        return church_id.startswith("study_intro")

    def _is_bom_summary_block(self, *, para_dict: Dict) -> bool:
        """Return True when a paragraph belongs to a BOM summary block.

        Args:
            para_dict: Paragraph payload.
        Returns:
            True for chapter summaries and their study intros.
        """

        return self._is_chapter_summary(para_dict=para_dict) or self._is_study_intro(
            para_dict=para_dict
        )

    def _summary_block_full_width(self, *, paragraphs: Sequence[Dict]) -> bool:
        """Return True when any summary paragraph is full width.

        Args:
            paragraphs: Summary block paragraphs.
        Returns:
            True when any paragraph is full width.
        """

        return any(self._is_full_width_paragraph(para_dict=p) for p in paragraphs)

    def _needs_summary_intro_gap(
        self, *, paragraphs: Sequence[Dict], index: int
    ) -> bool:
        """Return True when a chapter summary is followed by a study intro.

        Args:
            paragraphs: Summary block paragraphs.
            index: Index of the current paragraph.
        Returns:
            True when the next paragraph is a study intro.
        """

        if index >= len(paragraphs) - 1:
            return False
        current = paragraphs[index]
        next_para = paragraphs[index + 1]
        return self._is_chapter_summary(para_dict=current) and self._is_study_intro(
            para_dict=next_para
        )

    def _prepare_context(self) -> None:
        """Initialize verse and footnote lookups.

        Returns:
            None.
        """

        self.footnotes_by_verse = _footnotes_by_verse(footnotes=self.chapter.footnotes)
        self.verse_lookup = {v.compare_id: v for v in self.chapter.verses}

    def _is_full_width_paragraph(self, *, para_dict: Dict) -> bool:
        """Return True when a paragraph should render full width.

        Args:
            para_dict: Paragraph payload.
        Returns:
            True when the paragraph should span the full body width.
        """

        if para_dict.get("full_width"):
            return True
        p_type = para_dict.get("type") or ""
        if p_type in {"book-title", "book-subtitle"}:
            return True
        if (para_dict.get("paragraphCategory") or "") == "book_summary":
            return True
        if (para_dict.get("paragraphCategory") or "") == "historical_narrative":
            return True
        if self.book.standard_work == "doctrine-and-covenants":
            if self.book.slug == "official-declarations":
                return True
            if p_type == "chapter-title":
                return True
            church_id = para_dict.get("churchId") or ""
            if church_id.startswith("study_intro"):
                return True
        return False

    def _handle_paragraph(self, *, para_dict: Dict) -> None:
        """Dispatch a paragraph dictionary to the right handler.

        Args:
            para_dict: Chapter paragraph payload.
        Returns:
            None.
        """

        category = para_dict.get("paragraphCategory") or ""
        p_type = para_dict.get("type")
        try:
            if p_type == "study-footnotes":
                return
            if p_type == "verse":
                self._handle_verse(para_dict=para_dict)
            elif p_type == "book-title":
                self._handle_book_title(para_dict=para_dict)
            elif p_type == "book-subtitle":
                if not self.book_subtitles_consumed:
                    self._handle_book_subtitle(para_dict=para_dict)
            elif p_type == "chapter-title":
                self._handle_chapter_title(para_dict=para_dict)
            elif p_type == "chapter-subtitle":
                pass
            elif p_type == "section-title":
                self._handle_section_title(para_dict=para_dict)
            elif p_type == "study-paragraph":
                self._handle_study_paragraph(para_dict=para_dict)
            elif p_type == "paragraph":
                self._handle_plain_paragraph(para_dict=para_dict)
            else:
                self._handle_plain_paragraph(para_dict=para_dict)
        finally:
            self.prev_paragraph_category = category

    def _collect_chapter_subtitles(self) -> List[str]:
        """Return chapter subtitle HTML strings.

        Returns:
            Subtitle HTML strings.
        """

        subtitles: List[str] = []
        for para_dict in self.chapter.paragraphs:
            if (para_dict.get("type") or "") == "chapter-subtitle":
                subtitles.append(para_dict.get("contentHtml") or "")
        return subtitles

    def _collect_book_subtitles(self) -> List[str]:
        """Return book subtitle HTML strings.

        Returns:
            Subtitle HTML strings.
        """

        subtitles: List[str] = []
        for para_dict in self.chapter.paragraphs:
            if (para_dict.get("type") or "") == "book-subtitle":
                subtitles.append(para_dict.get("contentHtml") or "")
        return subtitles

    def _consume_chapter_subtitles(self) -> List[str]:
        """Return and clear the cached chapter subtitles.

        Returns:
            Subtitle HTML strings.
        """

        subtitles = self.chapter_subtitles
        self.chapter_subtitles = []
        return subtitles

    def _consume_book_subtitles(self) -> List[str]:
        """Return and clear cached book subtitles.

        Returns:
            Subtitle HTML strings.
        """

        subtitles = self.book_subtitles
        self.book_subtitles = []
        self.book_subtitles_consumed = True
        return subtitles
