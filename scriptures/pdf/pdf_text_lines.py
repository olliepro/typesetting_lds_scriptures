"""Flowable construction and line grouping for scripture text."""

from __future__ import annotations

from .pdf_text_flowables import SectionTitleFlowable, StackedFlowable
from .pdf_text_line_builder import ChapterLineBuilder
from .pdf_text_line_entry import _full_width_header, _line_items_for_chapter
from .pdf_text_line_helpers import (
    _body_style_for_group,
    _group_lines,
    _paragraphs_from_group,
    _paragraphs_from_lines,
    _partition_paragraphs,
    _split_before_first_verse,
    _split_intro_paragraphs,
    _split_small_prefix,
    _study_paragraphs,
    _text_width_for_html,
    _uppercase_html_text,
)

__all__ = [
    "ChapterLineBuilder",
    "SectionTitleFlowable",
    "StackedFlowable",
    "_body_style_for_group",
    "_full_width_header",
    "_group_lines",
    "_line_items_for_chapter",
    "_paragraphs_from_group",
    "_paragraphs_from_lines",
    "_partition_paragraphs",
    "_split_before_first_verse",
    "_split_intro_paragraphs",
    "_split_small_prefix",
    "_study_paragraphs",
    "_text_width_for_html",
    "_uppercase_html_text",
]
