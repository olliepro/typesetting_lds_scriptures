"""Entry points for building chapter line items."""

from __future__ import annotations

from typing import Dict, List

from pyphen import Pyphen
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from ..models import Book, Chapter
from .pdf_text_html import _paragraph_from_html
from .pdf_text_line_builder import ChapterLineBuilder
from .pdf_types import FlowItem


def _line_items_for_chapter(
    *,
    chapter: Chapter,
    book: Book,
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen,
    column_width: float,
    body_width: float,
    inline_preface: bool,
    include_chapter_heading: bool,
) -> List[FlowItem]:
    """Convert a chapter into line-sized FlowItems ready for pagination.

    Args:
        chapter: Chapter to render.
        book: Parent book information.
        styles: Paragraph styles for the document.
        hyphenator: Hyphenation helper for body text.
        column_width: Target column width for wrapping.
        inline_preface: Whether to inline preface blocks for this chapter.
        include_chapter_heading: Whether to render an in-column chapter heading.
    Returns:
        A list of FlowItems where each verse is split into single-line units.
    """

    builder = ChapterLineBuilder(
        chapter=chapter,
        book=book,
        styles=styles,
        hyphenator=hyphenator,
        column_width=column_width,
        body_width=body_width,
        inline_preface=inline_preface,
        include_chapter_heading=include_chapter_heading,
    )
    return builder.build()


def _full_width_header(
    *, chapter: Chapter, styles: Dict[str, ParagraphStyle], hyphenator: Pyphen
) -> List[Paragraph]:
    """Build full-width header blocks for the top of a page.

    Args:
        chapter: Chapter containing header blocks.
        styles: Paragraph styles for the document.
        hyphenator: Hyphenation helper.
    Returns:
        List of Paragraph flowables.
    """

    blocks: List[Paragraph] = []
    for block_type, html in chapter.header_blocks:
        style = styles["header"] if "title" in block_type else styles["preface"]
        para = _paragraph_from_html(
            html=html,
            style=style,
            hyphenator=hyphenator,
            insert_hair_space=True,
        )
        if getattr(style, "backColor", None) is None:
            debug_style = ParagraphStyle(
                name=_debug_style_name(style_name=style.name),
                parent=style,
                borderWidth=0.6,
                borderColor=colors.green,
                borderPadding=2,
            )
            para = Paragraph(para.text, debug_style)
        blocks.append(para)
    return blocks


def _debug_style_name(*, style_name: str) -> str:
    """Return a debug style name variant.

    Args:
        style_name: Base style name.
    Returns:
        Debug style name.
    """

    return f"{style_name}-debug"
