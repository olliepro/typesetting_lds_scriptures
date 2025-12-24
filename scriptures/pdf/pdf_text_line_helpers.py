"""Helper utilities for chapter line building."""

from __future__ import annotations

from typing import Callable, Dict, List, Sequence, cast
import re

from bs4 import BeautifulSoup
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, Paragraph

from .pdf_text_html import _normalize_breaks
from .pdf_types import FlowItem


def _uppercase_html_text(*, html: str) -> str:
    """Return HTML with text nodes uppercased.

    Args:
        html: Source HTML fragment.
    Returns:
        HTML string with uppercased text nodes.
    """

    normalized = _normalize_breaks(html=html)
    soup = BeautifulSoup(normalized, "html.parser")
    for node in soup.find_all(string=True):
        node.replace_with(node.upper())
    return soup.decode_contents()


def _text_width_for_html(*, html: str, style: ParagraphStyle) -> float:
    """Return the rendered width of HTML text for a style.

    Args:
        html: Source HTML fragment.
        style: Paragraph style for font metrics.
    Returns:
        Width in points for the plain text.
    """

    text = BeautifulSoup(html, "html.parser").get_text()
    font_name = style.fontName or "Times-Roman"
    font_size = style.fontSize or 12
    from reportlab.pdfbase import pdfmetrics

    return pdfmetrics.stringWidth(text, font_name, font_size)


def _split_small_prefix(*, html: str) -> tuple[list[str], str]:
    """Split a leading <small> prefix from a title HTML string.

    Args:
        html: HTML fragment that may include a leading <small> tag.
    Returns:
        Tuple of (small_htmls, remaining_html). small_htmls is empty when absent.

    Example:
        >>> _split_small_prefix(html="<small>Intro</small> Book")
        (['Intro'], ' Book')
    """

    soup = BeautifulSoup(html, "html.parser")
    small = soup.find("small")
    if small is None:
        return [], html
    small_text = small.decode_contents()
    small.extract()
    remaining = soup.decode_contents().lstrip()
    remaining = re.sub(r"^<br\s*/?>", "", remaining, flags=re.IGNORECASE).lstrip()
    return [small_text], remaining


def _split_intro_paragraphs(
    *, paragraphs: Sequence[Dict], is_intro: Callable[[Dict], bool]
) -> tuple[List[Dict], List[Dict]]:
    """Split leading intro paragraphs from the remainder.

    Args:
        paragraphs: Paragraph dictionaries in chapter order.
        is_intro: Callable that returns True for intro paragraphs.
    Returns:
        Tuple of (intro_paragraphs, remaining_paragraphs).
    """

    intro: List[Dict] = []
    remainder: List[Dict] = []
    in_intro = True
    for para in paragraphs:
        if in_intro and is_intro(para):
            intro.append(para)
            continue
        in_intro = False
        remainder.append(para)
    return intro, remainder


def _partition_paragraphs(
    *,
    paragraphs: Sequence[Dict],
    predicate: Callable[[Dict], bool],
) -> tuple[List[Dict], List[Dict]]:
    """Partition paragraphs by a predicate, preserving order.

    Args:
        paragraphs: Paragraph dictionaries in chapter order.
        predicate: Callable that returns True for selected paragraphs.
    Returns:
        Tuple of (matching_paragraphs, remaining_paragraphs).
    """

    matching: List[Dict] = []
    remaining: List[Dict] = []
    for para in paragraphs:
        if predicate(para):
            matching.append(para)
        else:
            remaining.append(para)
    return matching, remaining


def _split_before_first_verse(
    *, paragraphs: Sequence[Dict]
) -> tuple[List[Dict], List[Dict]]:
    """Split paragraphs at the first verse paragraph.

    Args:
        paragraphs: Paragraph dictionaries in chapter order.
    Returns:
        Tuple of (pre_verse, post_verse) lists.
    """

    pre: List[Dict] = []
    for idx, para in enumerate(paragraphs):
        if (para.get("type") or "") == "verse":
            return pre, list(paragraphs[idx:])
        pre.append(para)
    return pre, []


def _paragraphs_from_lines(
    *, lines: Sequence[FlowItem], styles: Dict[str, ParagraphStyle]
) -> List[Flowable]:
    """Recombine line HTML into paragraphs per verse.

    Args:
        lines: FlowItems in reading order.
        styles: Style lookup by name.
    Returns:
        List of Paragraph objects.
    """

    if not lines:
        return []
    paragraphs: List[Flowable] = []
    for group in _group_lines(lines=lines):
        paragraphs.extend(_paragraphs_from_group(group=group, styles=styles))
    return paragraphs


def _group_lines(*, lines: Sequence[FlowItem]) -> List[List[FlowItem]]:
    """Group lines by verse and segment index.

    Args:
        lines: FlowItems to group.
    Returns:
        List of FlowItem groups.
    """

    groups: List[List[FlowItem]] = []
    current: List[FlowItem] = [lines[0]]
    current_verse = lines[0].verse
    for line in lines[1:]:
        if line.verse == current_verse and line.segment_index == current[-1].segment_index:
            current.append(line)
            continue
        groups.append(current)
        current = [line]
        current_verse = line.verse
    groups.append(current)
    return groups


def _paragraphs_from_group(
    *, group: Sequence[FlowItem], styles: Dict[str, ParagraphStyle]
) -> List[Flowable]:
    """Return paragraphs for a FlowItem group.

    Args:
        group: FlowItems for a paragraph/segment.
        styles: Style lookup by name.
    Returns:
        List of Paragraphs for the group.
    """

    first = group[0]
    if first.style_name == "spacer":
        return [item.paragraph for item in group]
    if first.style_name in {
        "chapter_heading_group",
        "section_heading_group",
        "book_title_group",
    }:
        return [first.paragraph]
    if first.style_name == "study":
        return _study_paragraphs(group=group)
    style_name = _body_style_for_group(group=group)
    text = " ".join(item.line_html for item in group)
    return [Paragraph(text, styles[style_name])]


def _study_paragraphs(*, group: Sequence[FlowItem]) -> List[Flowable]:
    """Return paragraphs for a study group with mixed styles.

    Args:
        group: FlowItems for a study paragraph.
    Returns:
        List of Paragraphs with correct styling.
    """

    paragraphs: List[Flowable] = []
    current_style = cast(Paragraph, group[0].paragraph).style
    buffer = group[0].line_html
    for item in group[1:]:
        style = cast(Paragraph, item.paragraph).style
        if style is current_style:
            buffer = f"{buffer} {item.line_html}"
            continue
        paragraphs.append(Paragraph(buffer, current_style))
        current_style = style
        buffer = item.line_html
    paragraphs.append(Paragraph(buffer, current_style))
    return paragraphs


def _body_style_for_group(*, group: Sequence[FlowItem]) -> str:
    """Return the style name for body-like groups with continuations.

    Args:
        group: FlowItems for the group.
    Returns:
        Style key for the paragraph.
    """

    first = group[0]
    base_style = None
    if first.style_name.startswith("body"):
        base_style = "body"
    elif first.style_name.startswith("historical_narrative"):
        base_style = "historical_narrative"
    elif first.style_name.startswith("declaration_body"):
        base_style = "declaration_body"
    elif first.style_name.startswith("declaration_excerpt"):
        base_style = "declaration_excerpt"
    if base_style is None:
        return first.style_name
    ends_mid_segment = group[-1].verse_line_index < group[-1].verse_line_count - 1
    if ends_mid_segment:
        return (
            f"{base_style}-justify-last"
            if first.first_line
            else f"{base_style}-cont-justify-last"
        )
    return base_style if first.first_line else f"{base_style}-cont"
