"""Verse handling mixin for chapter line building."""

from __future__ import annotations

from typing import Dict

from reportlab.platypus import Paragraph

from ..models import FootnoteEntry, Verse
from .pdf_text_line_base import _LineBuilderBase
from .pdf_text_html import _ensure_verse_number_span, _split_on_breaks, _verse_markup, _wrap_paragraph
from .pdf_text_line_footnotes import _collect_line_footnotes, _footnote_map


class _VersesMixin(_LineBuilderBase):
    """Mixin for verse paragraph handling."""

    def _handle_verse(self, *, para_dict: Dict) -> None:
        """Append flow items for a verse paragraph.

        Args:
            para_dict: Paragraph data with verse metadata.
        Returns:
            None.
        """

        verse = self._verse_from_para(para_dict=para_dict)
        if verse is None:
            return
        full_width = self._is_full_width_paragraph(para_dict=para_dict)
        segments = _split_on_breaks(html=_verse_markup(verse))
        footnote_map = _footnote_map(
            verse_number=verse.number,
            footnotes_by_verse=self.footnotes_by_verse,
        )
        assigned_letters: set[str] = set()
        for seg_idx, segment_html in enumerate(segments):
            if not segment_html.strip():
                self._append_blank_segment(
                    verse=verse, seg_idx=seg_idx, full_width=full_width
                )
                continue
            self._append_segment_lines(
                verse=verse,
                seg_idx=seg_idx,
                segment_html=segment_html,
                footnote_map=footnote_map,
                assigned_letters=assigned_letters,
                full_width=full_width,
            )
        self._append_unmatched_footnotes(
            footnote_map=footnote_map,
            assigned_letters=assigned_letters,
        )

    def _verse_from_para(self, *, para_dict: Dict) -> Verse | None:
        """Return the verse object for a paragraph dictionary.

        Args:
            para_dict: Paragraph data with compareId.
        Returns:
            Verse instance or None when missing.
        """

        compare_id = para_dict.get("compareId")
        if not isinstance(compare_id, str):
            return None
        return self.verse_lookup.get(compare_id)

    def _append_blank_segment(
        self, *, verse: Verse, seg_idx: int, full_width: bool
    ) -> None:
        """Insert a spacer line for an empty verse segment.

        Args:
            verse: Verse to associate with the spacer.
            seg_idx: Segment index within the verse.
        Returns:
            None.
        """

        spacer_para = Paragraph("&nbsp;", self.styles["body-cont"])
        self.items.append(
            self._flow_item(
                paragraph=spacer_para,
                line_html="&nbsp;",
                style_name="body-cont",
                first_line=False,
                verse=verse.number,
                footnotes=[],
                full_width=full_width,
                segment_index=seg_idx,
                verse_line_index=0,
                verse_line_count=1,
            )
        )

    def _append_segment_lines(
        self,
        *,
        verse: Verse,
        seg_idx: int,
        segment_html: str,
        footnote_map: Dict[str, FootnoteEntry],
        assigned_letters: set[str],
        full_width: bool,
    ) -> None:
        """Append flow items for a verse segment.

        Args:
            verse: Verse data object.
            seg_idx: Segment index within the verse.
            segment_html: HTML fragment for the segment.
            footnote_map: Mapping of footnote letters to entries.
            assigned_letters: Set tracking already assigned letters.
        Returns:
            None.
        """

        wrap_width = self.body_width if full_width else self.column_width
        _, line_htmls = _wrap_paragraph(
            html=segment_html,
            style=self.styles["body"],
            hyphenator=self.hyphenator,
            width=wrap_width,
        )
        total_lines = len(line_htmls)
        for line_idx, line_html in enumerate(line_htmls):
            self._append_segment_line(
                verse=verse,
                seg_idx=seg_idx,
                line_idx=line_idx,
                total_lines=total_lines,
                line_html=line_html,
                footnote_map=footnote_map,
                assigned_letters=assigned_letters,
                full_width=full_width,
            )

    def _append_segment_line(
        self,
        *,
        verse: Verse,
        seg_idx: int,
        line_idx: int,
        total_lines: int,
        line_html: str,
        footnote_map: Dict[str, FootnoteEntry],
        assigned_letters: set[str],
        full_width: bool,
    ) -> None:
        """Append a single FlowItem for a verse line.

        Args:
            verse: Verse data object.
            seg_idx: Segment index within the verse.
            line_idx: Line index within the segment.
            total_lines: Total line count for the segment.
            line_html: HTML fragment for the line.
            footnote_map: Mapping of footnote letters to entries.
            assigned_letters: Set tracking already assigned letters.
        Returns:
            None.
        """

        is_first_line = seg_idx == 0 and line_idx == 0
        style_name = "body" if is_first_line else "body-cont"
        if is_first_line:
            line_html = _ensure_verse_number_span(
                line_html=line_html, verse_number=verse.number
            )
        line_para = Paragraph(line_html, self.styles[style_name])
        notes = _collect_line_footnotes(
            line_html=line_html,
            footnote_map=footnote_map,
            assigned_letters=assigned_letters,
        )
        self.items.append(
            self._flow_item(
                paragraph=line_para,
                line_html=line_html,
                style_name=style_name,
                first_line=is_first_line,
                verse=verse.number,
                footnotes=notes,
                full_width=full_width,
                segment_index=seg_idx,
                verse_line_index=line_idx,
                verse_line_count=total_lines,
            )
        )

    def _append_unmatched_footnotes(
        self,
        *,
        footnote_map: Dict[str, FootnoteEntry],
        assigned_letters: set[str],
    ) -> None:
        """Append any unmatched footnotes to the last item.

        Args:
            footnote_map: Mapping of footnote letters to entries.
            assigned_letters: Set of letters already assigned.
        Returns:
            None.
        """

        if not footnote_map or not self.items:
            return
        if assigned_letters == set(footnote_map):
            return
        for key, entry in footnote_map.items():
            if key not in assigned_letters:
                self.items[-1].footnotes.append(entry)
