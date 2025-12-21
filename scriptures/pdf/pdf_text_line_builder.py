"""Chapter line builder orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle

from ..models import Book, Chapter, FootnoteEntry, Verse
from .pdf_text_line_mixins_build import _BuildMixin
from .pdf_text_line_mixins_paragraphs import _ParagraphsMixin
from .pdf_text_line_mixins_titles import _TitlesMixin
from .pdf_text_line_mixins_verses import _VersesMixin
from .pdf_types import FlowItem


@dataclass(slots=True)
class ChapterLineBuilder(_BuildMixin, _TitlesMixin, _ParagraphsMixin, _VersesMixin):
    """Build FlowItem lines for a chapter.

    Args:
        chapter: Chapter to render.
        book: Parent book information.
        styles: Paragraph styles for the document.
        hyphenator: Hyphenation helper for body text.
        column_width: Target column width for wrapping.
        body_width: Full body width for full-width paragraphs.
        inline_preface: Whether to inline preface blocks for this chapter.
        include_chapter_heading: Whether to render an in-column chapter heading.
    """

    chapter: Chapter
    book: Book
    styles: Dict[str, ParagraphStyle]
    hyphenator: Pyphen
    column_width: float
    body_width: float
    inline_preface: bool
    include_chapter_heading: bool
    items: List[FlowItem] = field(default_factory=list)
    footnotes_by_verse: Dict[str, List[FootnoteEntry]] = field(
        init=False, default_factory=dict
    )
    verse_lookup: Dict[str, Verse] = field(init=False, default_factory=dict)
    para_counter: int = 0
    prev_historical_narrative: bool = False
    chapter_subtitles: List[str] = field(default_factory=list)
    book_subtitles: List[str] = field(default_factory=list)
    book_subtitles_consumed: bool = False
