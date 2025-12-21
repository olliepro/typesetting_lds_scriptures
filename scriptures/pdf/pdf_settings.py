"""Fonts, styles, and layout settings for PDF generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .pdf_constants import EPSILON

PAGE_SCALE = 0.7


@dataclass(slots=True)
class PageSettings:
    """Geometry constants used during layout.

    Example:
        >>> settings = PageSettings()
        >>> settings.body_width > 0
        True
    """

    page_width: float = letter[0] * PAGE_SCALE
    page_height: float = letter[1] * PAGE_SCALE
    margin_left: float = 0.65 * inch * PAGE_SCALE
    margin_right: float = 0.65 * inch * PAGE_SCALE
    margin_top: float = 0.75 * inch * PAGE_SCALE
    margin_bottom: float = 0.5 * inch * PAGE_SCALE
    column_gap: float = 12.0 * PAGE_SCALE
    footnote_rule_height: float = 0.0
    header_gap: float = 6.0 * PAGE_SCALE
    footnote_extra_buffer: float = 0.0
    text_extra_buffer: float = 0.0
    footnote_row_padding: float = 0.0
    footnote_chapter_width: float = 6.0 * PAGE_SCALE
    footnote_verse_width: float = 12.0 * PAGE_SCALE
    footnote_letter_width: float = 6.0 * PAGE_SCALE
    footnote_letter_gap: float = 1 * PAGE_SCALE
    font_name: str = "Palatino"
    font_bold_name: str = "Palatino-Bold"
    footnote_font_size: float = 8.0
    separator_line_color: colors.Color = colors.lightgrey
    separator_line_width: float = 0.8
    debug_borders: bool = False

    @property
    def body_width(self) -> float:
        """Return the width available for content inside margins.

        Returns:
            Width in points.
        """

        return self.page_width - self.margin_left - self.margin_right

    @property
    def body_height(self) -> float:
        """Return the height available for content inside margins.

        Returns:
            Height in points.
        """

        return self.page_height - self.margin_top - self.margin_bottom + EPSILON

    def text_column_width(self) -> float:
        """Return the width of each text column.

        Returns:
            Column width in points.
        """

        return self.body_width / 2

    def footnote_column_width(self) -> float:
        """Return the width of each footnote column.

        Returns:
            Column width in points.
        """

        return (self.body_width - 2 * self.column_gap) / 3

    def footnote_text_width(self) -> float:
        """Return text width within a footnote column.

        Returns:
            Width in points for the footnote text cell.
        """

        return (
            self.footnote_column_width()
            - self.footnote_chapter_width
            - self.footnote_verse_width
            - self.footnote_letter_width
            - self.footnote_letter_gap
        )


def register_palatino() -> str:
    """Register the Palatino font family and return its base name.

    Returns:
        The registered regular font name.

    Example:
        >>> name = register_palatino()
        >>> isinstance(name, str)
        True
    """

    font_path = "/System/Library/Fonts/Palatino.ttc"
    regular = "Palatino"
    bold = "Palatino-Bold"
    italic = "Palatino-Italic"
    bold_italic = "Palatino-BoldItalic"
    if regular not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular, font_path))
    if bold not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold, font_path, subfontIndex=2))
    if italic not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(italic, font_path, subfontIndex=1))
    if bold_italic not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_italic, font_path, subfontIndex=3))
    pdfmetrics.registerFontFamily(
        regular,
        normal=regular,
        bold=bold,
        italic=italic,
        boldItalic=bold_italic,
    )
    return regular


def register_hebrew_fallback() -> str:
    """Register a Hebrew-capable font and return its name.

    Returns:
        Font name that supports Hebrew glyphs; Palatino if no candidate exists.

    Example:
        >>> name = register_hebrew_fallback()
        >>> isinstance(name, str)
        True
    """

    candidates = [
        ("/System/Library/Fonts/Supplemental/ArialHebrew.ttf", "ArialHebrew"),
        ("/System/Library/Fonts/Supplemental/ArialUnicode.ttf", "ArialUnicode"),
        ("/System/Library/Fonts/SFHebrew.ttf", "SFHebrew"),
        ("/System/Library/Fonts/SFHebrewRounded.ttf", "SFHebrewRounded"),
        ("/Library/Fonts/Arial Unicode.ttf", "ArialUnicodeFull"),
        ("/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf", "NotoSansHebrew"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans"),
    ]
    for path, name in candidates:
        if not Path(path).exists():
            continue
        if name not in pdfmetrics.getRegisteredFontNames():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                continue
        return name
    return "Palatino"


def build_styles(font_name: str) -> Dict[str, ParagraphStyle]:
    """Create paragraph styles used in the document.

    Args:
        font_name: Base font name registered with ReportLab.
    Returns:
        Mapping of style keys to ParagraphStyle objects.

    Example:
        >>> styles = build_styles("Palatino")
        >>> "body" in styles
        True
    """

    base = getSampleStyleSheet()
    italic_name = f"{font_name}-Italic"
    hebrew_font = register_hebrew_fallback()
    core = _core_styles(
        base=base,
        font_name=font_name,
        italic_name=italic_name,
        hebrew_font=hebrew_font,
    )
    footnote = _footnote_style_map(
        base=base,
        font_name=font_name,
        italic_name=italic_name,
    )
    return {**core, **footnote}


def _core_styles(
    *,
    base,
    font_name: str,
    italic_name: str,
    hebrew_font: str,
) -> Dict[str, ParagraphStyle]:
    """Return core (non-footnote) paragraph styles.

    Args:
        base: Sample stylesheet.
        font_name: Base font name.
        italic_name: Italic font name.
        hebrew_font: Hebrew fallback font name.
    Returns:
        Mapping of core style keys to ParagraphStyle objects.
    """

    body = _body_style(base=base, font_name=font_name, italic_name=italic_name)
    body_cont = _continuation_style(style=body)
    header = _header_style(base=base, font_name=font_name)
    book_title = _book_title_style(header=header)
    book_subtitle = _book_subtitle_style(base=base, font_name=font_name)
    book_summary = _book_summary_style(body=body)
    psalm_headnote = _psalm_headnote_style(body=body, italic_name=italic_name)
    historical_narrative = _historical_narrative_style(body=body)
    historical_narrative_cont = _continuation_style(style=historical_narrative)
    decorative_divider = _decorative_divider_style(body=body)
    section = _section_style(
        header=header, font_name=font_name, hebrew_font=hebrew_font
    )
    chapter_heading = _chapter_heading_style(base=base, font_name=font_name)
    preface = _preface_style(base=base, italic_name=italic_name)
    study, study_first = _study_styles(body=body, italic_name=italic_name)
    return {
        "body": body,
        "body-cont": body_cont,
        "body-justify-last": _body_justify_last(style=body),
        "body-cont-justify-last": _body_cont_justify_last(style=body_cont),
        "header": header,
        "book_title": book_title,
        "book_subtitle": book_subtitle,
        "book_summary": book_summary,
        "psalm_headnote": psalm_headnote,
        "historical_narrative": historical_narrative,
        "historical_narrative-cont": historical_narrative_cont,
        "historical_narrative-justify-last": _body_justify_last(
            style=historical_narrative
        ),
        "historical_narrative-cont-justify-last": _body_cont_justify_last(
            style=historical_narrative_cont
        ),
        "decorative_divider": decorative_divider,
        "section": section,
        "chapter_heading": chapter_heading,
        "preface": preface,
        "study": study,
        "study_first": study_first,
    }


def _footnote_style_map(
    *, base, font_name: str, italic_name: str
) -> Dict[str, ParagraphStyle]:
    """Return footnote paragraph styles.

    Args:
        base: Sample stylesheet.
        font_name: Base font name.
        italic_name: Italic font name.
    Returns:
        Mapping of footnote style keys to ParagraphStyle objects.
    """

    footnote, footnote_ch, footnote_letter = _footnote_styles(
        base=base,
        font_name=font_name,
        italic_name=italic_name,
    )
    return {
        "footnote": footnote,
        "footnote_ch": footnote_ch,
        "footnote_letter": footnote_letter,
    }


def _style_map(
    *,
    body: ParagraphStyle,
    body_cont: ParagraphStyle,
    body_last: ParagraphStyle,
    body_cont_last: ParagraphStyle,
    header: ParagraphStyle,
    section: ParagraphStyle,
    chapter_heading: ParagraphStyle,
    preface: ParagraphStyle,
    study: ParagraphStyle,
    study_first: ParagraphStyle,
    footnote: ParagraphStyle,
    footnote_ch: ParagraphStyle,
    footnote_letter: ParagraphStyle,
) -> Dict[str, ParagraphStyle]:
    """Return a mapping of style keys to ParagraphStyle objects.

    Args:
        body: Body style.
        body_cont: Continuation body style.
        body_last: Body style with justified last line.
        body_cont_last: Continuation style with justified last line.
        header: Header style.
        section: Section style.
        chapter_heading: Chapter heading style.
        preface: Preface style.
        study: Study style.
        study_first: Study-first style.
        footnote: Footnote style.
        footnote_ch: Footnote chapter style.
        footnote_letter: Footnote letter style.
    Returns:
        Style mapping.
    """

    return {
        "body": body,
        "body-cont": body_cont,
        "body-justify-last": body_last,
        "body-cont-justify-last": body_cont_last,
        "header": header,
        "section": section,
        "chapter_heading": chapter_heading,
        "preface": preface,
        "study": study,
        "study_first": study_first,
        "footnote": footnote,
        "footnote_ch": footnote_ch,
        "footnote_letter": footnote_letter,
    }


def _body_style(*, base, font_name: str, italic_name: str) -> ParagraphStyle:
    """Return the base body style with italic font metadata.

    Args:
        base: ReportLab sample styles.
        font_name: Base font name.
        italic_name: Italic font name.
    Returns:
        Configured ParagraphStyle for body text.
    """

    body = ParagraphStyle(
        "Body",
        parent=base["Normal"],
        fontName=font_name,
        fontSize=11,
        leading=13,
        alignment=TA_JUSTIFY,
        spaceAfter=0,
        spaceBefore=0,
        leftIndent=0,
        firstLineIndent=8,
    )
    return body


def _header_style(*, base, font_name: str) -> ParagraphStyle:
    """Return the header style.

    Args:
        base: ReportLab sample styles.
        font_name: Base font name.
    Returns:
        Header ParagraphStyle.
    """

    return ParagraphStyle(
        "Header",
        parent=base["Heading2"],
        fontName=font_name,
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=6,
        keepWithNext=False,
    )


def _book_title_style(*, header: ParagraphStyle) -> ParagraphStyle:
    """Return the book title style.

    Args:
        header: Base header style.
    Returns:
        Book title ParagraphStyle.
    """

    return ParagraphStyle(
        "BookTitle",
        parent=header,
        fontSize=26,
        leading=30,
        alignment=TA_CENTER,
        spaceBefore=38,
        spaceAfter=10,
    )


def _book_subtitle_style(*, base, font_name: str) -> ParagraphStyle:
    """Return the book subtitle style.

    Args:
        base: ReportLab sample styles.
        font_name: Base font name.
    Returns:
        Book subtitle ParagraphStyle.
    """

    return ParagraphStyle(
        "BookSubtitle",
        parent=base["Normal"],
        fontName=font_name,
        fontSize=12,
        leading=15,
        alignment=TA_CENTER,
        spaceBefore=0,
        spaceAfter=10,
    )


def _book_summary_style(*, body: ParagraphStyle) -> ParagraphStyle:
    """Return the book summary paragraph style.

    Args:
        body: Base body style.
    Returns:
        Book summary ParagraphStyle.
    """

    return ParagraphStyle(
        "BookSummary",
        parent=body,
        leftIndent=0,
        firstLineIndent=0,
        spaceAfter=0,
    )


def _psalm_headnote_style(*, body: ParagraphStyle, italic_name: str) -> ParagraphStyle:
    """Return the Psalm headnote paragraph style.

    Args:
        body: Base body style for leading reference.
        italic_name: Italic font name.
    Returns:
        Psalm headnote ParagraphStyle.
    """

    return ParagraphStyle(
        "PsalmHeadnote",
        parent=body,
        fontName=italic_name,
        fontSize=8,
        leading=body.leading,
        alignment=TA_CENTER,
        leftIndent=0,
        firstLineIndent=0,
        spaceAfter=0,
    )


def _historical_narrative_style(*, body: ParagraphStyle) -> ParagraphStyle:
    """Return the historical narrative paragraph style.

    Args:
        body: Base body style.
    Returns:
        Historical narrative ParagraphStyle.
    """

    return ParagraphStyle(
        "HistoricalNarrative",
        parent=body,
        fontSize=8,
        leading=10,
        spaceAfter=0,
    )


def _decorative_divider_style(*, body: ParagraphStyle) -> ParagraphStyle:
    """Return the decorative divider paragraph style.

    Args:
        body: Base body style.
    Returns:
        Decorative divider ParagraphStyle.
    """

    return ParagraphStyle(
        "DecorativeDivider",
        parent=body,
        alignment=TA_CENTER,
        leftIndent=0,
        firstLineIndent=0,
        spaceAfter=0,
    )


def _section_style(
    *, header: ParagraphStyle, font_name: str, hebrew_font: str
) -> ParagraphStyle:
    """Return the section title style with Hebrew font metadata.

    Args:
        header: Base header style.
        font_name: Base font name.
        hebrew_font: Font name to use for Hebrew glyphs.
    Returns:
        Section ParagraphStyle.
    """

    section = ParagraphStyle(
        "Section",
        parent=header,
        # fontSize=11,
        leading=13,
        spaceBefore=13,
        # spaceAfter=6.5,
        fontName=font_name,
    )
    setattr(section, "hebrew_font_name", hebrew_font)
    return section


def _chapter_heading_style(*, base, font_name: str) -> ParagraphStyle:
    """Return the chapter heading style.

    Args:
        base: ReportLab sample styles.
        font_name: Base font name.
    Returns:
        Chapter heading ParagraphStyle.
    """

    return ParagraphStyle(
        "ChapterHeading",
        parent=base["Normal"],
        fontName=font_name,
        fontSize=11,
        leading=13,
        alignment=TA_CENTER,
        spaceBefore=0,
        spaceAfter=0,
    )


def _preface_style(*, base, italic_name: str) -> ParagraphStyle:
    """Return the preface style.

    Args:
        base: ReportLab sample styles.
        italic_name: Italic font name.
    Returns:
        Preface ParagraphStyle.
    """

    return ParagraphStyle(
        "Preface",
        parent=base["Normal"],
        fontName=italic_name,
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        spaceAfter=6,
        italic=True,
    )


def _study_styles(
    *, body: ParagraphStyle, italic_name: str
) -> tuple[ParagraphStyle, ParagraphStyle]:
    """Return study paragraph styles for multi-line notes.

    Args:
        body: Base body style.
        italic_name: Italic font name.
    Returns:
        Tuple of (study, study_first) styles.
    """

    study = ParagraphStyle(
        "Study",
        parent=body,
        fontName=italic_name,
        italic=True,
        spaceAfter=0,
        leftIndent=0,
        firstLineIndent=0,
        justifyLastLine=0,
    )
    study_first = ParagraphStyle(
        "StudyFirst",
        parent=study,
        justifyLastLine=1,
    )
    return study, study_first


def _body_justify_last(*, style: ParagraphStyle) -> ParagraphStyle:
    """Return the body style variant that justifies last line.

    Args:
        style: Base body style.
    Returns:
        ParagraphStyle with justifyLastLine enabled.
    """

    return ParagraphStyle(
        "BodyJustifyLast",
        parent=style,
        justifyLastLine=1,
    )


def _body_cont_justify_last(*, style: ParagraphStyle) -> ParagraphStyle:
    """Return the continuation style variant that justifies last line.

    Args:
        style: Continuation body style.
    Returns:
        ParagraphStyle with justifyLastLine enabled.
    """

    return ParagraphStyle(
        "BodyContJustifyLast",
        parent=style,
        justifyLastLine=1,
    )


def _footnote_styles(
    *, base, font_name: str, italic_name: str
) -> tuple[ParagraphStyle, ParagraphStyle, ParagraphStyle]:
    """Return footnote styles for text, chapter, and letter cells.

    Args:
        base: ReportLab sample styles.
        font_name: Base font name.
        italic_name: Italic font name.
    Returns:
        Tuple of (footnote, footnote_ch, footnote_letter) styles.
    """

    footnote = ParagraphStyle(
        "Footnote",
        parent=base["Normal"],
        fontName=font_name,
        fontSize=7.8,
        leading=8.0,
        alignment=TA_LEFT,
        leftIndent=0,
        spaceAfter=0,
        spaceBefore=0,
    )
    footnote_ch = ParagraphStyle(
        "FootnoteCh",
        parent=footnote,
        fontName="Palatino-Bold",
    )
    footnote_letter = ParagraphStyle(
        "FootnoteLetter",
        parent=footnote,
        fontName=italic_name,
        italic=True,
    )
    footnote.tabs = [
        (0, TA_LEFT, 0),
        (18, TA_RIGHT, 0),
        (30, TA_LEFT, 0),
        (34, TA_LEFT, 0),
    ]
    return footnote, footnote_ch, footnote_letter


def _continuation_style(*, style: ParagraphStyle) -> ParagraphStyle:
    """Return a copy of a style with no first-line indent.

    Args:
        style: Base ParagraphStyle.
    Returns:
        ParagraphStyle configured without a first-line indent.
    """

    if style.name.endswith("-cont"):
        return style
    return ParagraphStyle(
        f"{style.name}-cont",
        parent=style,
        firstLineIndent=0,
    )
