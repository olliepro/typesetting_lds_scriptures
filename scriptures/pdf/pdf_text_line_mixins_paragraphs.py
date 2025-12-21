"""Paragraph handling mixin for chapter line building."""

from __future__ import annotations

from typing import Dict, List, Sequence

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, Paragraph, Spacer

from ..layout_utils import measure_height
from .pdf_text_line_base import _LineBuilderBase
from ..models import FootnoteEntry
from .pdf_text_flowables import StackedFlowable
from .pdf_text_html import _paragraph_from_html, _wrap_paragraph
from .pdf_types import FlowItem


class _ParagraphsMixin(_LineBuilderBase):
    """Mixin for study/plain paragraph handling."""

    def _handle_study_paragraph(self, *, para_dict: Dict) -> None:
        """Append flow items for a study paragraph.

        Args:
            para_dict: Paragraph data with study HTML.
        Returns:
            None.
        """

        self.para_counter += 1
        paragraph_key = f"study-paragraph-{self.para_counter}"
        study_html = para_dict.get("contentHtml", "")
        full_width = self._is_full_width_paragraph(para_dict=para_dict)
        if self._is_jsh_section_summary(para_dict=para_dict):
            body_style = self.styles["body"]
            gap = body_style.leading or body_style.fontSize or 0
            self._insert_spacer(
                height=gap,
                paragraph_key=f"{paragraph_key}-jsh-summary-gap",
                full_width=full_width,
            )
        wrap_width = self.column_width if not full_width else self.body_width
        _, line_htmls = _wrap_paragraph(
            html=study_html,
            style=self.styles["study"],
            hyphenator=self.hyphenator,
            width=wrap_width,
        )
        grouped = self._maybe_merge_with_heading(
            line_htmls=line_htmls, full_width=full_width
        )
        self._append_study_lines(
            line_htmls=line_htmls,
            paragraph_key=paragraph_key,
            grouped_with_heading=grouped,
            full_width=full_width,
        )
        self._append_study_padding(paragraph_key=paragraph_key, full_width=full_width)

    def _handle_plain_paragraph(self, *, para_dict: Dict) -> None:
        """Append flow items for a non-verse paragraph.

        Args:
            para_dict: Paragraph data with HTML content.
        Returns:
            None.
        """

        self.para_counter += 1
        paragraph_key = f"paragraph-{self.para_counter}"
        full_width = self._is_full_width_paragraph(para_dict=para_dict)
        html = para_dict.get("contentHtml", "")
        if self._is_jsh_section_summary(para_dict=para_dict):
            body_style = self.styles["body"]
            gap = body_style.leading or body_style.fontSize or 0
            self._insert_spacer(
                height=gap,
                paragraph_key=f"{paragraph_key}-jsh-summary-gap",
                full_width=full_width,
            )
        if self._is_jsh_historical_narrative(para_dict=para_dict):
            if not self.prev_historical_narrative:
                body_style = self.styles["body"]
                gap = body_style.leading or body_style.fontSize or 0
                self._insert_spacer(
                    height=gap,
                    paragraph_key=f"{paragraph_key}-hist-gap",
                    full_width=full_width,
                )
            self._append_wrapped_lines(
                html=html,
                style=self.styles["historical_narrative"],
                style_name="historical_narrative",
                paragraph_key=paragraph_key,
                full_width=full_width,
            )
            return
        if self._is_decorative_divider(para_dict=para_dict):
            self._append_wrapped_lines(
                html=html,
                style=self.styles["decorative_divider"],
                style_name="decorative_divider",
                paragraph_key=paragraph_key,
                full_width=full_width,
            )
            return
        if (para_dict.get("paragraphCategory") or "") == "psalm_headnote":
            self._append_wrapped_lines(
                html=html,
                style=self.styles["psalm_headnote"],
                style_name="psalm_headnote",
                paragraph_key=paragraph_key,
                full_width=full_width,
            )
            return
        if (para_dict.get("paragraphCategory") or "") == "book_summary":
            body_style = self.styles["body"]
            gap = body_style.leading or body_style.fontSize or 0
            self._append_wrapped_lines(
                html=html,
                style=self.styles["book_summary"],
                style_name="book_summary",
                paragraph_key=paragraph_key,
                full_width=full_width,
            )
            self._insert_spacer(
                height=gap,
                paragraph_key=f"{paragraph_key}-summary-gap",
                full_width=full_width,
            )
            return
        self._append_wrapped_lines(
            html=html,
            style=self.styles["body"],
            style_name="body",
            paragraph_key=paragraph_key,
            full_width=full_width,
        )

    def _maybe_merge_with_heading(
        self, *, line_htmls: List[str], full_width: bool
    ) -> bool:
        """Merge a study paragraph with a preceding heading when present.

        Args:
            line_htmls: Wrapped line HTMLs for the study paragraph.
        Returns:
            True when a heading was merged.
        """

        if not line_htmls or not self.items:
            return False
        if self.items[-1].style_name not in {"chapter_heading_group", "section_heading_group"}:
            return False
        heading_item = self.items.pop()
        heading_lines = getattr(heading_item.paragraph, "logical_lines", 1)
        group_lines = heading_lines + 1
        first_line_html = line_htmls.pop(0)
        is_single = len(line_htmls) == 0
        first_style = self.styles["study"] if is_single else self.styles["study_first"]
        first_line_para = Paragraph(first_line_html, first_style)
        grouped = self._heading_group_flowable(
            heading=heading_item.paragraph,
            first_line=first_line_para,
            logical_lines=group_lines,
        )
        self.items.append(
            self._flow_item(
                paragraph=grouped,
                line_html=f"{heading_item.line_html} + {first_line_html}",
                style_name=heading_item.style_name,
                first_line=True,
                verse=heading_item.verse,
                footnotes=[],
                full_width=full_width,
            )
        )
        return True

    def _heading_group_flowable(
        self,
        *,
        heading: Flowable,
        first_line: Paragraph,
        logical_lines: int,
    ) -> StackedFlowable:
        """Return a stacked flowable for heading + first study line.

        Args:
            heading: Heading flowable to keep with the study line.
            first_line: First study paragraph line.
            logical_lines: Logical line count for balancing.
        Returns:
            StackedFlowable keeping the header and first line together.
        """

        content: List[Flowable] = []
        space_before = heading.getSpaceBefore()
        space_after = heading.getSpaceAfter()
        if space_before:
            content.append(Spacer(1, space_before))
        content.append(heading)
        if space_after:
            content.append(Spacer(1, space_after))
        content.append(first_line)
        return StackedFlowable(content, logical_lines=logical_lines)

    def _append_study_lines(
        self,
        *,
        line_htmls: Sequence[str],
        paragraph_key: str,
        grouped_with_heading: bool,
        full_width: bool,
    ) -> None:
        """Append FlowItems for each study line.

        Args:
            line_htmls: Study line HTML fragments.
            paragraph_key: Key for paragraph grouping.
            grouped_with_heading: Whether first line was merged with heading.
        Returns:
            None.
        """

        is_single = len(line_htmls) == 1
        for idx, line_html in enumerate(line_htmls):
            is_last = idx == len(line_htmls) - 1
            style = self.styles["study"] if is_single or is_last else self.styles["study_first"]
            line_para = Paragraph(line_html, style)
            self.items.append(
                self._flow_item(
                    paragraph=line_para,
                    line_html=line_html,
                    style_name="study",
                    first_line=idx == 0 and not grouped_with_heading,
                    verse=paragraph_key,
                    footnotes=[],
                    full_width=full_width,
                )
            )

    def _append_study_padding(
        self, *, paragraph_key: str, full_width: bool = False
    ) -> None:
        """Append a padding line after a study paragraph.

        Args:
            paragraph_key: Key for paragraph grouping.
        Returns:
            None.
        """

        padding_para = Paragraph("&nbsp;", self.styles["body-cont"])
        setattr(padding_para, "logical_lines", 1)
        self.items.append(
            self._flow_item(
                paragraph=padding_para,
                line_html="&nbsp;",
                style_name="body-cont",
                first_line=False,
                verse=f"{paragraph_key}-padding",
                footnotes=[],
                full_width=full_width,
            )
        )

    def _append_single_paragraph(
        self,
        *,
        html: str,
        style: ParagraphStyle,
        style_name: str,
        paragraph_key: str,
        full_width: bool,
    ) -> None:
        """Append a single FlowItem for a paragraph.

        Args:
            html: HTML fragment to render.
            style: Paragraph style.
            style_name: Style key for later reconstruction.
            paragraph_key: Key for paragraph grouping.
            full_width: Whether to render across full body width.
        Returns:
            None.
        """

        paragraph = _paragraph_from_html(
            html=html,
            style=style,
            hyphenator=self.hyphenator,
            insert_hair_space=True,
        )
        line_html = getattr(paragraph, "_orig_html", html)
        self.items.append(
            self._flow_item(
                paragraph=paragraph,
                line_html=line_html,
                style_name=style_name,
                first_line=True,
                verse=paragraph_key,
                footnotes=[],
                full_width=full_width,
            )
        )

    def _append_wrapped_lines(
        self,
        *,
        html: str,
        style: ParagraphStyle,
        style_name: str,
        paragraph_key: str,
        full_width: bool = False,
    ) -> None:
        """Append FlowItems for wrapped paragraph lines.

        Args:
            html: HTML fragment to wrap.
            style: Paragraph style.
            style_name: Name key of the style.
            paragraph_key: Key for paragraph grouping.
        Returns:
            None.
        """

        width = self.column_width if not full_width else self.body_width
        _, line_htmls = _wrap_paragraph(
            html=html,
            style=style,
            hyphenator=self.hyphenator,
            width=width,
        )
        total_lines = len(line_htmls)
        for idx, line_html in enumerate(line_htmls):
            line_para = Paragraph(line_html, style)
            self.items.append(
                self._flow_item(
                    paragraph=line_para,
                    line_html=line_html,
                    style_name=style_name,
                    first_line=idx == 0,
                    verse=paragraph_key,
                    footnotes=[],
                    full_width=full_width,
                    verse_line_index=idx,
                    verse_line_count=total_lines,
                )
            )

    def _insert_spacer(
        self, *, height: float, paragraph_key: str, full_width: bool = False
    ) -> None:
        """Add a blank FlowItem to preserve vertical spacing.

        Args:
            height: Spacer height in points.
            paragraph_key: Key for paragraph grouping.
        Returns:
            None.
        """

        if height <= 0:
            return
        spacer = Spacer(1, height)
        self.items.append(
            self._flow_item(
                paragraph=spacer,
                line_html="",
                style_name="spacer",
                first_line=False,
                verse=paragraph_key,
                footnotes=[],
                full_width=full_width,
            )
        )

    def _flow_item(
        self,
        *,
        paragraph: Flowable,
        line_html: str,
        style_name: str,
        first_line: bool,
        verse: str | None,
        footnotes: List[FootnoteEntry],
        full_width: bool,
        segment_index: int = 0,
        verse_line_index: int = 0,
        verse_line_count: int = 1,
    ) -> FlowItem:
        """Create a FlowItem with common metadata populated.

        Args:
            paragraph: Flowable to render.
            line_html: HTML for the line.
            style_name: Style key.
            first_line: Whether this line starts a paragraph/segment.
            verse: Verse number or paragraph key.
            footnotes: Footnotes linked to this line.
            segment_index: Verse segment index.
            verse_line_index: Line index within the verse.
            verse_line_count: Total line count for the verse.
        Returns:
            FlowItem populated with chapter and book metadata.
        """

        width = self.body_width if full_width else self.column_width
        return FlowItem(
            paragraph=paragraph,
            height=measure_height(flowable=paragraph, width=width),
            line_html=line_html,
            style_name=style_name,
            first_line=first_line,
            standard_work=self.chapter.standard_work,
            book_slug=self.book.slug,
            book_name=self.book.name,
            chapter=self.chapter.number,
            chapter_title=self.chapter.title,
            verse=verse,
            footnotes=footnotes,
            segment_index=segment_index,
            verse_line_index=verse_line_index,
            verse_line_count=verse_line_count,
            full_width=full_width,
        )
