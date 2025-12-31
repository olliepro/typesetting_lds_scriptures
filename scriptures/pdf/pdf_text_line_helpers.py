"""Helper utilities for chapter line building."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, cast
import re

from bs4 import BeautifulSoup, NavigableString, Tag
from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, Paragraph

from .pdf_text_html import _normalize_breaks, _paragraph_from_html
from .pdf_types import FlowItem


@dataclass(slots=True)
class ParagraphSource:
    """Paragraph with its source line HTML fragments.

    Args:
        paragraph: Flowable used for layout.
        line_htmls: Source line HTML fragments.
        recombined_html: HTML used to build the paragraph.
        style_name: Style key or name used for rendering.
    """

    paragraph: Flowable
    line_htmls: List[str]
    recombined_html: str
    style_name: str


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
    *,
    lines: Sequence[FlowItem],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen | None,
) -> List[Flowable]:
    """Recombine line HTML into paragraphs per verse.

    Args:
        lines: FlowItems in reading order.
        styles: Style lookup by name.
        hyphenator: Hyphenation helper for rehyphenated paragraphs.
    Returns:
        List of Paragraph objects.

    Example:
        >>> _paragraphs_from_lines(lines=[], styles={}, hyphenator=None)
        []
    """

    if not lines:
        return []
    paragraphs: List[Flowable] = []
    for group in _group_lines(lines=lines):
        paragraphs.extend(
            _paragraphs_from_group(
                group=group,
                styles=styles,
                hyphenator=hyphenator,
            )
        )
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
    *,
    group: Sequence[FlowItem],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen | None,
) -> List[Flowable]:
    """Return paragraphs for a FlowItem group.

    Args:
        group: FlowItems for a paragraph/segment.
        styles: Style lookup by name.
        hyphenator: Hyphenation helper for rehyphenated paragraphs.
    Returns:
        List of Paragraphs for the group.
    """

    sources = _paragraph_sources_from_group(
        group=group,
        styles=styles,
        hyphenator=hyphenator,
    )
    return [source.paragraph for source in sources]


def _paragraph_sources_from_group(
    *,
    group: Sequence[FlowItem],
    styles: Dict[str, ParagraphStyle],
    hyphenator: Pyphen | None,
) -> List[ParagraphSource]:
    """Return paragraph sources for a FlowItem group.

    Args:
        group: FlowItems for a paragraph/segment.
        styles: Style lookup by name.
        hyphenator: Hyphenation helper for rehyphenated paragraphs.
    Returns:
        List of ParagraphSource entries for the group.
    """

    first = group[0]
    if first.style_name == "spacer":
        return [_existing_paragraph_source(item=item) for item in group]
    if first.style_name in {
        "chapter_heading_group",
        "section_heading_group",
        "book_title_group",
    }:
        return [_existing_paragraph_source(item=first)]
    if first.style_name == "study":
        return _study_paragraph_sources(group=group, hyphenator=hyphenator)
    style_name = _body_style_for_group(group=group)
    style = styles[style_name]
    line_htmls = [item.line_html for item in group]
    use_recombined = _group_is_split(group=group)
    return [
        _build_paragraph_source(
            line_htmls=line_htmls,
            style=style,
            style_name=style_name,
            hyphenator=hyphenator,
            source_html=group[0].source_html,
            use_recombined=use_recombined,
        )
    ]


def _study_paragraphs(
    *, group: Sequence[FlowItem], hyphenator: Pyphen | None
) -> List[Flowable]:
    """Return paragraphs for a study group with mixed styles.

    Args:
        group: FlowItems for a study paragraph.
        hyphenator: Hyphenation helper for rehyphenated paragraphs.
    Returns:
        List of Paragraphs with correct styling.
    """

    sources = _study_paragraph_sources(group=group, hyphenator=hyphenator)
    return [source.paragraph for source in sources]


def _study_paragraph_sources(
    *, group: Sequence[FlowItem], hyphenator: Pyphen | None
) -> List[ParagraphSource]:
    """Return paragraph sources for a study group with mixed styles.

    Args:
        group: FlowItems for a study paragraph.
        hyphenator: Hyphenation helper for rehyphenated paragraphs.
    Returns:
        List of ParagraphSource entries for the study group.
    """

    sources: List[ParagraphSource] = []
    current_style = cast(Paragraph, group[0].paragraph).style
    buffer: List[str] = [group[0].line_html]
    buffer_items: List[FlowItem] = [group[0]]
    for item in group[1:]:
        style = cast(Paragraph, item.paragraph).style
        if style is current_style:
            buffer.append(item.line_html)
            buffer_items.append(item)
            continue
        sources.append(
            _build_paragraph_source(
                line_htmls=buffer,
                style=current_style,
                style_name=current_style.name,
                hyphenator=hyphenator,
                source_html=buffer_items[0].source_html,
                use_recombined=_group_is_split(group=buffer_items),
            )
        )
        current_style = style
        buffer = [item.line_html]
        buffer_items = [item]
    sources.append(
        _build_paragraph_source(
            line_htmls=buffer,
            style=current_style,
            style_name=current_style.name,
            hyphenator=hyphenator,
            source_html=buffer_items[0].source_html,
            use_recombined=_group_is_split(group=buffer_items),
        )
    )
    return sources


def _build_paragraph_source(
    *,
    line_htmls: Sequence[str],
    style: ParagraphStyle,
    style_name: str | None = None,
    hyphenator: Pyphen | None = None,
    source_html: str | None = None,
    use_recombined: bool = True,
) -> ParagraphSource:
    """Return a ParagraphSource for the given line HTMLs.

    Args:
        line_htmls: Line HTML fragments to combine.
        style: Paragraph style for the paragraph.
        style_name: Optional style name override.
        hyphenator: Hyphenation helper for rehyphenated paragraphs.
        source_html: Original hyphenated HTML for the paragraph/segment.
        use_recombined: Whether to build from recombined line HTML.
    Returns:
        ParagraphSource with recombined HTML and Paragraph.
    """

    recombined_html = " ".join(line_htmls)
    final_html = recombined_html
    if not use_recombined and source_html:
        final_html = source_html
    elif hyphenator is not None:
        final_html = _ensure_inline_spacing_html(
            html=recombined_html,
            tag_names=("sup", "i"),
        )
    resolved_style = style_name or style.name
    paragraph = Paragraph(final_html, style)
    if hyphenator is not None and use_recombined:
        paragraph = _paragraph_from_html(
            html=final_html,
            style=style,
            hyphenator=hyphenator,
            insert_hair_space=False,
        )
    return ParagraphSource(
        paragraph=paragraph,
        line_htmls=list(line_htmls),
        recombined_html=recombined_html,
        style_name=resolved_style,
    )


def _ensure_inline_spacing_html(
    *, html: str, tag_names: Sequence[str]
) -> str:
    """Insert a span-wrapped space before selected inline tags when needed.

    Args:
        html: HTML fragment to normalize.
        tag_names: Tag names that require leading spaces when adjacent.
    Returns:
        HTML with ``<span> </span>`` inserted before adjacent tags.

    Example:
        >>> _ensure_inline_spacing_html(html="word<sup>a</sup>", tag_names=("sup",))
        'word<span> </span><sup>a</sup>'
    """

    soup = BeautifulSoup(html, "html.parser")
    for tag in list(soup.find_all(tag_names)):
        _insert_inline_space(tag=tag, soup=soup)
    return soup.decode_contents()


_LEADING_PUNCTUATION = {".", ",", ";", ":", "!", "?", ")", "]", "}"}
_DASH_CHARACTERS = {
    "-",
    "\u2010",
    "\u2011",
    "\u2012",
    "\u2013",
    "\u2014",
}


def _ends_with_dash(*, text: str) -> bool:
    """Return True when text ends with a dash character.

    Args:
        text: Text to inspect.
    Returns:
        True when the last non-whitespace character is a dash.

    Example:
        >>> _ends_with_dash(text="said\\u2014")
        True
    """

    stripped = text.rstrip()
    if not stripped:
        return False
    return stripped[-1] in _DASH_CHARACTERS


def _starts_with_punctuation(*, tag: Tag) -> bool:
    """Return True when a tag's text begins with punctuation.

    Args:
        tag: Inline tag to inspect.
    Returns:
        True when the first non-whitespace character is punctuation.
    """

    text = tag.get_text()
    stripped = text.lstrip()
    if not stripped:
        return False
    return stripped[0] in _LEADING_PUNCTUATION


def _skip_inline_space_for_tag(*, tag: Tag) -> bool:
    """Return True when a tag should never receive an inserted space.

    Args:
        tag: Inline tag to inspect.
    Returns:
        True when spacing should be skipped for the tag.
    """

    if tag.find_parent("sup") is not None:
        return True
    return tag.name == "i" and _previous_element_is_sup(tag=tag)


def _skip_inline_space_for_prev_sibling(
    *, prev_sibling: Tag | NavigableString | None, punctuation_sensitive: bool
) -> bool:
    """Return True when the previous sibling already enforces spacing.

    Args:
        prev_sibling: Immediate previous sibling node.
        punctuation_sensitive: Whether punctuation spacing rules apply.
    Returns:
        True when no additional space should be inserted.
    """

    if isinstance(prev_sibling, NavigableString) and not str(prev_sibling).strip():
        return not punctuation_sensitive
    if (
        isinstance(prev_sibling, Tag)
        and prev_sibling.name == "span"
        and not prev_sibling.get_text(strip=True)
    ):
        if not punctuation_sensitive:
            return True
        prev_sibling.extract()
    return False


def _previous_non_whitespace_element(
    *, tag: Tag
) -> tuple[Tag | NavigableString | None, list[NavigableString]]:
    """Return the previous non-whitespace element and skipped whitespace.

    Args:
        tag: Inline tag to inspect.
    Returns:
        Tuple of (previous_element, skipped_whitespace_nodes).
    """

    prev = tag.previous_element
    skipped_ws: list[NavigableString] = []
    while prev:
        if isinstance(prev, NavigableString):
            if str(prev).strip():
                break
            skipped_ws.append(prev)
            prev = prev.previous_element
            continue
        if isinstance(prev, Tag):
            if prev is tag or prev in tag.parents:
                prev = prev.previous_element
                continue
            break
        prev = prev.previous_element
    if prev is None or not isinstance(prev, (NavigableString, Tag)):
        return None, skipped_ws
    return prev, skipped_ws


def _trim_previous_text(*, prev: Tag | NavigableString) -> None:
    """Trim trailing whitespace from a previous NavigableString.

    Args:
        prev: Previous element to trim when it is a NavigableString.
    Returns:
        None.
    """

    if isinstance(prev, NavigableString):
        trimmed = re.sub(r"\s+$", "", str(prev))
        prev.replace_with(trimmed)


def _insert_inline_space(*, tag: Tag, soup: BeautifulSoup) -> None:
    """Insert a span-wrapped space before an inline tag when needed.

    Args:
        tag: Inline tag to inspect.
        soup: Parsed HTML container.
    Returns:
        None.
    """

    punctuation_sensitive = tag.name == "i" and _starts_with_punctuation(tag=tag)
    if _skip_inline_space_for_tag(tag=tag):
        return
    if _skip_inline_space_for_prev_sibling(
        prev_sibling=tag.previous_sibling,
        punctuation_sensitive=punctuation_sensitive,
    ):
        return
    prev, skipped_ws = _previous_non_whitespace_element(tag=tag)
    if prev is None:
        return
    prev_text = str(prev) if isinstance(prev, NavigableString) else prev.get_text()
    if not skipped_ws and _ends_with_dash(text=prev_text):
        return
    for ws in skipped_ws:
        ws.extract()
    _trim_previous_text(prev=prev)
    if punctuation_sensitive:
        return
    space_tag = soup.new_tag("span")
    space_tag.string = " "
    tag.insert_before(space_tag)


def _previous_element_is_sup(*, tag: Tag) -> bool:
    """Return True when the previous element is a superscript marker.

    Args:
        tag: Inline tag to inspect.
    Returns:
        True when the tag follows a superscript marker.
    """

    prev_sibling = tag.previous_sibling
    if isinstance(prev_sibling, Tag):
        if prev_sibling.name == "sup":
            return True
        if prev_sibling.find("sup") is not None:
            return True
    prev = tag.previous_element
    while prev and isinstance(prev, NavigableString) and not str(prev).strip():
        prev = prev.previous_element
    if not isinstance(prev, Tag):
        return False
    if prev.name == "sup":
        return True
    if prev.find_parent("sup") is not None:
        return True
    return prev.name == "font" and prev.find("sup") is not None


def _group_is_split(*, group: Sequence[FlowItem]) -> bool:
    """Return True when the group is missing paragraph lines.

    Args:
        group: FlowItems for a paragraph/segment slice.
    Returns:
        True when the paragraph continues outside the slice.
    """

    first = group[0]
    last = group[-1]
    if first.is_verse:
        starts_at_begin = first.verse_line_index == 0
        ends_at_end = last.verse_line_index >= last.verse_line_count - 1
        return not (starts_at_begin and ends_at_end)
    if not first.first_line:
        return True
    return last.verse_line_count > 1 and last.verse_line_index < last.verse_line_count - 1


def _existing_paragraph_source(*, item: FlowItem) -> ParagraphSource:
    """Return a ParagraphSource using the existing flowable.

    Args:
        item: FlowItem providing a flowable and line HTML.
    Returns:
        ParagraphSource using the existing flowable.
    """

    return ParagraphSource(
        paragraph=item.paragraph,
        line_htmls=[item.line_html],
        recombined_html=item.line_html,
        style_name=item.style_name,
    )


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
