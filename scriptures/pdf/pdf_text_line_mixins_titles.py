"""Title handling mixin for chapter line building."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, Paragraph, Spacer

from ..layout_utils import measure_height
from .pdf_text_line_base import _LineBuilderBase
from .pdf_text_flowables import SectionTitleFlowable, StackedFlowable
from .pdf_text_html import _apply_hebrew_font, _line_fragments, _paragraph_from_html
from .pdf_text_line_helpers import _split_small_prefix, _text_width_for_html, _uppercase_html_text


class _TitlesMixin(_LineBuilderBase):
    """Mixin for book/chapter/section title handling."""

    def _handle_section_title(self, *, para_dict: Dict) -> None:
        """Append flow items for a section title paragraph.

        Args:
            para_dict: Paragraph data with section title HTML.
        Returns:
            None.
        """

        self.para_counter += 1
        paragraph_key = f"section-title-{self.para_counter}"
        full_width = self._is_full_width_paragraph(para_dict=para_dict)
        if not self.items:
            style = self.styles["section"]
            if self.book.slug == "official-declarations":
                style = self.styles["declaration_section"]
            self._insert_spacer(
                height=style.spaceBefore or 0,
                paragraph_key=f"{paragraph_key}-lead",
                full_width=full_width,
            )
        section_html = para_dict.get("contentHtml", "")
        hebrew_font = getattr(self.styles["section"], "hebrew_font_name", None)
        section_html = _apply_hebrew_font(html=section_html, hebrew_font=hebrew_font)
        style = self.styles["section"]
        style_name = "section"
        if self.book.slug == "official-declarations":
            section_html = _uppercase_html_text(html=section_html)
            style = self.styles["declaration_section"]
            style_name = "declaration_section"
            self.declaration_excerpt_mode = self._is_declaration_excerpt_title(
                html=section_html
            )
        else:
            self.declaration_excerpt_mode = False
        self._append_wrapped_lines(
            html=section_html,
            style=style,
            style_name=style_name,
            paragraph_key=paragraph_key,
            full_width=full_width,
        )
        self._insert_spacer(
            height=style.spaceAfter or 0,
            paragraph_key=f"{paragraph_key}-trail",
            full_width=full_width,
        )

    def _handle_book_title(self, *, para_dict: Dict) -> None:
        """Append flow items for a book title paragraph.

        Args:
            para_dict: Paragraph data with book title HTML.
        Returns:
            None.
        """

        self.para_counter += 1
        paragraph_key = f"book-title-{self.para_counter}"
        raw_html = para_dict.get("contentHtml", "")
        if self.book.slug == "official-declarations":
            html = _uppercase_html_text(html=raw_html)
            self._append_single_paragraph(
                html=html,
                style=self.styles["declaration_title"],
                style_name="declaration_title",
                paragraph_key=paragraph_key,
                full_width=self._is_full_width_paragraph(para_dict=para_dict),
            )
            return
        pretitle_htmls, title_html = _split_small_prefix(html=raw_html)
        html = _uppercase_html_text(html=title_html)
        subtitles = self._consume_book_subtitles()
        full_width = self._is_full_width_paragraph(para_dict=para_dict)
        if subtitles or pretitle_htmls:
            grouped = self._book_title_group_flowable(
                title_html=html,
                pretitle_htmls=pretitle_htmls,
                subtitle_htmls=subtitles,
            )
            self.items.append(
                self._flow_item(
                    paragraph=grouped,
                    line_html=html,
                    style_name="book_title_group",
                    first_line=True,
                    verse=paragraph_key,
                    footnotes=[],
                    full_width=full_width,
                )
            )
            return
        self._append_single_paragraph(
            html=html,
            style=self.styles["book_title"],
            style_name="book_title",
            paragraph_key=paragraph_key,
            full_width=full_width,
        )

    def _is_declaration_excerpt_title(self, *, html: str) -> bool:
        """Return True when the section title is the excerpts heading.

        Args:
            html: Section title HTML.
        Returns:
            True for the excerpts heading.
        """

        return "EXCERPTS FROM" in html.upper()

    def _handle_book_subtitle(self, *, para_dict: Dict) -> None:
        """Append flow items for a book subtitle paragraph.

        Args:
            para_dict: Paragraph data with subtitle HTML.
        Returns:
            None.
        """

        self.para_counter += 1
        paragraph_key = f"book-subtitle-{self.para_counter}"
        html = _uppercase_html_text(html=para_dict.get("contentHtml", ""))
        self._append_single_paragraph(
            html=html,
            style=self.styles["book_subtitle"],
            style_name="book_subtitle",
            paragraph_key=paragraph_key,
            full_width=self._is_full_width_paragraph(para_dict=para_dict),
        )

    def _handle_chapter_title(self, *, para_dict: Dict) -> None:
        """Append flow items for a chapter title paragraph.

        Args:
            para_dict: Paragraph data with chapter title HTML.
        Returns:
            None.
        """

        if self.include_chapter_heading:
            return
        self.para_counter += 1
        paragraph_key = f"chapter-title-{self.para_counter}"
        full_width = self._is_full_width_paragraph(para_dict=para_dict)
        html = para_dict.get("contentHtml", "")
        subtitles = self._consume_chapter_subtitles()
        if subtitles and not self._is_dc_section_title(para_dict=para_dict):
            html = "<br/>".join([html, *subtitles])
        if self._is_dc_section_title(para_dict=para_dict):
            section_flowable, line_html = self._section_title_flowable(
                html=html, style=self.styles["header"]
            )
            self.items.append(
                self._flow_item(
                    paragraph=section_flowable,
                    line_html=line_html,
                    style_name="section_heading_group",
                    first_line=True,
                    verse=paragraph_key,
                    footnotes=[],
                    full_width=True,
                )
            )
            return
        style_name = "section_heading_group" if full_width else "header"
        self._append_single_paragraph(
            html=html,
            style=self.styles["header"],
            style_name=style_name,
            paragraph_key=paragraph_key,
            full_width=full_width,
        )

    def _is_dc_section_title(self, *, para_dict: Dict) -> bool:
        """Return True when the paragraph is a D&C section title.

        Args:
            para_dict: Paragraph data with title metadata.
        Returns:
            True when the paragraph is a D&C section heading.
        """

        if self.book.standard_work != "doctrine-and-covenants":
            return False
        if self.book.slug == "official-declarations":
            return False
        if (para_dict.get("type") or "") != "chapter-title":
            return False
        title = (para_dict.get("content") or para_dict.get("contentHtml") or "").strip()
        return title.lower().startswith("section")

    def _section_title_flowable(
        self, *, html: str, style: ParagraphStyle
    ) -> tuple[Flowable, str]:
        """Return a flowable for an uppercased section title with a bar.

        Args:
            html: Raw title HTML.
            style: Paragraph style for the title.
        Returns:
            Tuple of (flowable, html) for the section title.
        """

        upper_html = _uppercase_html_text(html=html)
        clean_style = ParagraphStyle(
            name=f"{style.name}-section",
            parent=style,
            spaceBefore=0,
            spaceAfter=0,
        )
        paragraph = _paragraph_from_html(
            html=upper_html,
            style=clean_style,
            hyphenator=self.hyphenator,
            insert_hair_space=True,
        )
        text_width = _text_width_for_html(html=upper_html, style=style)
        flowable = SectionTitleFlowable(
            paragraph=paragraph,
            text_width=text_width,
            line_gap=max(1.0, style.fontSize * 0.2),
            line_thickness=0.6,
            line_color=style.textColor or colors.black,
        )
        flowable.spaceBefore = style.spaceBefore or 0
        flowable.spaceAfter = style.spaceAfter or 0
        return flowable, getattr(paragraph, "_orig_html", upper_html)

    def _book_title_group_flowable(
        self,
        *,
        title_html: str,
        pretitle_htmls: Sequence[str],
        subtitle_htmls: Sequence[str],
    ) -> StackedFlowable:
        """Return a stacked flowable for a book title with subtitles.

        Args:
            title_html: Uppercased title HTML.
            pretitle_htmls: Subtitle HTML strings to render above the title.
            subtitle_htmls: Subtitle HTML strings.
        Returns:
            StackedFlowable containing the title and subtitles.
        """

        title_style, subtitle_style, content = self._book_title_group_content(
            title_html=title_html,
            pretitle_htmls=pretitle_htmls,
            subtitle_htmls=subtitle_htmls,
        )
        grouped = StackedFlowable(
            content, logical_lines=self._paragraph_line_count(flowables=content)
        )
        grouped.spaceBefore = title_style.spaceBefore or 0
        grouped.spaceAfter = subtitle_style.spaceAfter or 0
        grouped.book_title_group = True
        return grouped

    def _book_title_group_content(
        self,
        *,
        title_html: str,
        pretitle_htmls: Sequence[str],
        subtitle_htmls: Sequence[str],
    ) -> tuple[ParagraphStyle, ParagraphStyle, List[Flowable]]:
        """Return styles and flowables for a grouped book title.

        Args:
            title_html: Uppercased title HTML.
            pretitle_htmls: Subtitle HTML strings to render above the title.
            subtitle_htmls: Subtitle HTML strings.
        Returns:
            Tuple of (title_style, subtitle_style, flowables).
        """

        title_style, subtitle_style, title_clean, subtitle_clean = (
            self._book_title_group_styles()
        )
        subtitle_gap, mid_gap = self._book_title_gaps(
            title_style=title_style, subtitle_style=subtitle_style
        )
        content: List[Flowable] = []
        content.extend(
            self._subtitle_flowables(
                htmls=pretitle_htmls,
                style=subtitle_clean,
                gap_between=0.0,
                gap_after=0.0,
            )
        )
        content.append(self._title_paragraph(html=title_html, style=title_clean))
        if subtitle_htmls and mid_gap:
            content.append(Spacer(1, mid_gap))
        content.extend(
            self._subtitle_flowables(
                htmls=subtitle_htmls,
                style=subtitle_clean,
                gap_between=subtitle_gap,
                gap_after=0.0,
            )
        )
        return title_style, subtitle_style, content

    def _book_title_gaps(
        self, *, title_style: ParagraphStyle, subtitle_style: ParagraphStyle
    ) -> tuple[float, float]:
        """Return subtitle gap and title-to-subtitle gap sizes.

        Args:
            title_style: Book title style.
            subtitle_style: Book subtitle style.
        Returns:
            Tuple of (subtitle_gap, mid_gap).
        """

        subtitle_gap = (subtitle_style.spaceAfter or 0) + (
            subtitle_style.spaceBefore or 0
        )
        mid_gap = (title_style.spaceAfter or 0) + (subtitle_style.spaceBefore or 0)
        return subtitle_gap, mid_gap

    def _title_paragraph(self, *, html: str, style: ParagraphStyle) -> Paragraph:
        """Return a Paragraph for a title line.

        Args:
            html: Title HTML fragment.
            style: Paragraph style for the title.
        Returns:
            Paragraph instance.
        """

        return _paragraph_from_html(
            html=html,
            style=style,
            hyphenator=self.hyphenator,
            insert_hair_space=True,
        )

    def _book_title_group_styles(
        self,
    ) -> tuple[ParagraphStyle, ParagraphStyle, ParagraphStyle, ParagraphStyle]:
        """Return styles for grouped book title rendering.

        Returns:
            Tuple of (title_style, subtitle_style, title_clean, subtitle_clean).
        """

        title_style = self.styles["book_title"]
        subtitle_style = self.styles["book_subtitle"]
        title_clean = ParagraphStyle(
            f"{title_style.name}-group", parent=title_style, spaceBefore=0, spaceAfter=0
        )
        subtitle_clean = ParagraphStyle(
            f"{subtitle_style.name}-group",
            parent=subtitle_style,
            spaceBefore=0,
            spaceAfter=0,
        )
        return title_style, subtitle_style, title_clean, subtitle_clean

    def _subtitle_flowables(
        self,
        *,
        htmls: Sequence[str],
        style: ParagraphStyle,
        gap_between: float,
        gap_after: float,
    ) -> List[Flowable]:
        """Return subtitle flowables with optional spacer gaps.

        Args:
            htmls: Subtitle HTML strings.
            style: Paragraph style for subtitles.
            gap_between: Gap between subtitle lines.
            gap_after: Gap after the final subtitle line.
        Returns:
            List of subtitle Paragraphs and Spacers.
        """

        content: List[Flowable] = []
        for idx, subtitle_html in enumerate(htmls):
            if idx > 0 and gap_between:
                content.append(Spacer(1, gap_between))
            subtitle_upper = _uppercase_html_text(html=subtitle_html)
            content.append(
                _paragraph_from_html(
                    html=subtitle_upper,
                    style=style,
                    hyphenator=self.hyphenator,
                    insert_hair_space=True,
                )
            )
        if htmls and gap_after:
            content.append(Spacer(1, gap_after))
        return content

    def _paragraph_line_count(self, *, flowables: Sequence[Flowable]) -> int:
        """Return the total wrapped line count for Paragraph flowables.

        Args:
            flowables: Flowables to inspect.
        Returns:
            Total line count, minimum of 1.
        """

        total = 0
        for flow in flowables:
            if isinstance(flow, Paragraph):
                total += len(_line_fragments(para=flow, width=self.body_width))
        return max(1, total)

    def _add_chapter_heading(self) -> None:
        """Append a chapter heading block.

        Returns:
            None.
        """

        heading_text = f"CHAPTER {self.chapter.number}"
        subtitles = self._consume_chapter_subtitles()
        if subtitles:
            heading_text = "<br/>".join([heading_text, *subtitles])
        heading_para = Paragraph(heading_text, self.styles["chapter_heading"])
        heading_height = measure_height(flowable=heading_para, width=self.column_width)
        line_height = (
            heading_para.style.leading
            or heading_para.style.fontSize
            or heading_height
        )
        gap = line_height * 0.5
        spacer_before = Spacer(1, gap)
        spacer_after = Spacer(1, gap)
        line_count = len(_line_fragments(para=heading_para, width=self.column_width))
        grouped = StackedFlowable(
            [spacer_before, heading_para, spacer_after],
            logical_lines=max(1, line_count + 1),
        )
        self.items.append(
            self._flow_item(
                paragraph=grouped,
                line_html=heading_text,
                style_name="chapter_heading_group",
                first_line=True,
                verse=f"chapter-{self.chapter.number}",
                footnotes=[],
                full_width=False,
            )
        )
