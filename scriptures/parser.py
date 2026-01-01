"""
Parsing helpers that convert scraper JSON into typed chapter objects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from .cleaning import clean_text, normalize_whitespace
from .models import Chapter, FootnoteEntry, FootnoteLink, Verse


_WORK_SEGMENT_TO_SLUG = {
    "ot": "old-testament",
    "nt": "new-testament",
    "bofm": "book-of-mormon",
    "dc-testament": "doctrine-and-covenants",
    "pgp": "pearl-of-great-price",
    "jst": "jst-appendix",
}

_SMALL_TAG_REPLACEMENT = '<font size="7">{}</font> '
_SMALL_CAPS_FONT_SIZE = 9
_SMALL_CAPS_WORD_RE = re.compile(r"[A-Za-z]+")
_DASH_CHARACTERS = {"-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014"}


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


def _footnote_prev_context(
    *, anchor: Tag
) -> tuple[Tag | NavigableString | None, list[NavigableString]]:
    """Return the previous non-whitespace element and skipped whitespace.

    Args:
        anchor: Footnote anchor tag being unwrapped.
    Returns:
        Tuple of (previous_element, skipped_whitespace_nodes).
    """

    prev = anchor.previous_element
    skipped_ws: list[NavigableString] = []
    while prev and isinstance(prev, NavigableString) and not str(prev).strip():
        skipped_ws.append(prev)
        prev = prev.previous_element
    if prev is None or not isinstance(prev, (NavigableString, Tag)):
        return None, skipped_ws
    return prev, skipped_ws


def _footnote_needs_space(*, prev: Tag | NavigableString | None) -> bool:
    """Return True when a footnote marker needs a leading space.

    Args:
        prev: Previous non-whitespace element.
    Returns:
        True when the superscript should be separated by a space.
    """

    if prev is None:
        return False
    if isinstance(prev, NavigableString):
        text = str(prev)
        if not text.strip():
            return False
        return not _ends_with_dash(text=text)
    text = prev.get_text()
    if _ends_with_dash(text=text):
        return False
    return True


def _strip_trailing_whitespace(node: NavigableString) -> bool:
    """Strip trailing whitespace from a NavigableString.

    Args:
        node: Text node to trim.
    Returns:
        True when trailing whitespace was removed.
    """

    text = str(node)
    match = re.search(r"\s+$", text)
    if not match:
        return False
    prefix = text[: match.start()]
    if not prefix.strip():
        node.extract()
        return True
    node.replace_with(prefix)
    return True


def _small_caps_text_nodes(
    *, text: str, soup: BeautifulSoup, font_size: int
) -> List[Tag | NavigableString]:
    """Return nodes for a small-caps text run with initial caps when capitalized.

    Args:
        text: Source text to convert.
        soup: BeautifulSoup instance for tag creation.
        font_size: Font size for the small-caps portion.
    Returns:
        List of nodes representing the transformed text.
    Example:
        >>> soup = BeautifulSoup("", "html.parser")
        >>> [str(node) for node in _small_caps_text_nodes(text="Lord", soup=soup, font_size=9)]  # doctest: +SKIP
        ['L', '<font size="9">ORD</font>']
    """

    nodes: List[Tag | NavigableString] = []
    pos = 0

    def small_caps_tag(value: str) -> Tag:
        font_tag = soup.new_tag("font")
        font_tag["size"] = str(font_size)
        font_tag.string = value
        return font_tag

    for match in _SMALL_CAPS_WORD_RE.finditer(text):
        start, end = match.span()
        word_raw = match.group(0)
        leading_space = ""
        if start > pos:
            between = text[pos:start]
            if between and not word_raw[0].isupper():
                stripped = between.rstrip()
                leading_space = between[len(stripped) :]
                between = stripped
            if between:
                nodes.append(NavigableString(between))
        word = word_raw.upper()
        if word_raw[0].isupper():
            nodes.append(NavigableString(word[0]))
            if word[1:]:
                nodes.append(small_caps_tag(word[1:]))
        else:
            nodes.append(small_caps_tag(f"{leading_space}{word}"))
        pos = end
    if pos < len(text):
        nodes.append(NavigableString(text[pos:]))
    return nodes


def _uppercase_span_nodes(*, span: Tag) -> List[Tag | NavigableString]:
    """Return nodes for an uppercase span with normal font size.

    Args:
        span: Uppercase span tag to transform.
    Returns:
        List of nodes representing the transformed text.
    Example:
        >>> soup = BeautifulSoup("", "html.parser")
        >>> span = soup.new_tag("span")
        >>> span["class"] = "uppercase"
        >>> span.append("Jesus")
        >>> [str(node) for node in _uppercase_span_nodes(span=span)]
        ['JESUS']
    """

    nodes: List[Tag | NavigableString] = []
    for child in list(span.contents):
        if isinstance(child, NavigableString):
            nodes.append(NavigableString(str(child).upper()))
        elif isinstance(child, Tag):
            child.extract()
            nodes.append(child)
    return nodes


def _shift_leading_space_after_italics(*, soup: BeautifulSoup) -> None:
    """Move a leading space after italics into the italic tag.

    Args:
        soup: Parsed HTML tree to mutate.
    Returns:
        None.
    Example:
        >>> soup = BeautifulSoup('word <i>in</i> Solomon', 'html.parser')
        >>> _shift_leading_space_after_italics(soup=soup)
        >>> soup.decode_contents()
        'word <i>in </i>Solomon'
    """

    for tag in list(soup.find_all("i")):
        next_node = tag.next_sibling
        if not isinstance(next_node, NavigableString):
            continue
        text = str(next_node)
        if not text.startswith(" "):
            continue
        if not tag.get_text().endswith(" "):
            space_tag = soup.new_tag("span")
            space_tag.string = " "
            tag.append(space_tag)
        remainder = text[1:]
        if remainder:
            next_node.replace_with(remainder)
        else:
            next_node.extract()


def _apply_verse_span_markup(*, html: str) -> str:
    """Convert verse span classes into ReportLab-friendly markup.

    Args:
        html: Verse HTML fragment that may contain ``small-caps``,
            ``uppercase``, or ``clarity-word`` span tags.
    Returns:
        HTML with small-caps converted to uppercase text inside a smaller
        <font> tag, uppercase spans converted to uppercase text, and clarity
        words wrapped in <i> tags.
    Example:
        >>> _apply_verse_span_markup(html='By the <span class="small-caps">Lord</span>.')  # doctest: +SKIP
        'By the L<font size="9">ORD</font>.'
    """

    soup = BeautifulSoup(html, "html.parser")
    for span in list(soup.select("span.small-caps")):
        new_nodes: List[Tag | NavigableString] = []
        for child in list(span.contents):
            if isinstance(child, NavigableString):
                new_nodes.extend(
                    _small_caps_text_nodes(
                        text=str(child),
                        soup=soup,
                        font_size=_SMALL_CAPS_FONT_SIZE,
                    )
                )
            elif isinstance(child, Tag):
                child.extract()
                new_nodes.append(child)
        for node in new_nodes:
            span.insert_before(node)
        span.decompose()
    for span in list(soup.select("span.uppercase")):
        new_nodes = _uppercase_span_nodes(span=span)
        for node in new_nodes:
            span.insert_before(node)
        span.decompose()
    for span in list(soup.select("span.clarity-word")):
        prev = span.previous_sibling
        needs_space = isinstance(prev, NavigableString) and _strip_trailing_whitespace(
            prev
        )
        if needs_space:
            space_tag = soup.new_tag("span")
            space_tag.string = " "
            span.insert_before(space_tag)
        italic_tag = soup.new_tag("i")
        for child in list(span.contents):
            italic_tag.append(child.extract())
        span.replace_with(italic_tag)
    _shift_leading_space_after_italics(soup=soup)
    return soup.decode_contents()


def _unwrap_footnote_links(html: str) -> str:
    """Replace anchor-based footnote markers with plain superscripts."""

    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select("a.footnote-link"):
        sup = anchor.find("sup")
        letter = sup.get("data-value") if sup else ""
        if sup:
            sup.decompose()
        # Add a leading space before the footnote marker when stuck to a word
        prev, skipped_ws = _footnote_prev_context(anchor=anchor)
        needs_space = _footnote_needs_space(prev=prev)

        new_sup = soup.new_tag("sup")
        new_sup.string = letter
        if needs_space:
            for ws in skipped_ws:
                ws.extract()
            if isinstance(prev, NavigableString):
                _strip_trailing_whitespace(prev)
            space_tag = soup.new_tag("span")
            space_tag.string = " "
            anchor.insert_before(space_tag)
        anchor.insert_before(new_sup)
        for child in list(anchor.children):
            anchor.insert_before(child)
        anchor.decompose()
    return soup.decode_contents()


def _strip_non_footnote_links(html: str) -> str:
    """Remove non-footnote anchors while preserving their inner text.

    Args:
        html: Raw HTML markup that may include anchor tags.
    Returns:
        HTML markup without non-footnote anchor tags.
    """

    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a"):
        anchor.unwrap()
    return soup.decode_contents()


def _normalize_inline_html(fragment: Tag | NavigableString) -> str:
    """Convert a BeautifulSoup fragment into ReportLab-friendly markup."""

    if isinstance(fragment, NavigableString):
        return clean_text(str(fragment))

    if fragment.name == "small":
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return _SMALL_TAG_REPLACEMENT.format(inner)

    if fragment.name in {"em", "i"}:
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return f"<i>{inner}</i>"

    if fragment.name in {"strong", "b"}:
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return f"<b>{inner}</b>"

    if fragment.name == "sup":
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return f"<sup>{inner}</sup>"

    if fragment.name == "a":
        href = fragment.get("href", "")
        inner = "".join(_normalize_inline_html(child) for child in fragment.children)
        return f'<a href="{href}">{inner}</a>'

    return "".join(_normalize_inline_html(child) for child in fragment.children)


def _parse_footnote_links(node: Tag, current_work: str) -> List[FootnoteLink]:
    """Extract FootnoteLink objects from a footnote <li> element."""

    links: List[FootnoteLink] = []
    for anchor in node.find_all("a", href=True):
        href = anchor["href"]
        parsed = urlparse(href)
        slug = ""
        path_parts = [p for p in parsed.path.split("/") if p]
        if (
            len(path_parts) >= 3
            and path_parts[0] == "study"
            and path_parts[1] == "scriptures"
        ):
            slug = _WORK_SEGMENT_TO_SLUG.get(path_parts[2], "")
        links.append(
            FootnoteLink(
                text=normalize_whitespace(anchor.get_text(strip=True)),
                href=href,
                is_internal=slug == current_work,
            )
        )
    return links


def _parse_footnotes(
    html: str,
    *,
    current_work: str,
    book_slug: str,
    chapter_number: str,
) -> List[FootnoteEntry]:
    """Parse the nested footnote list into FootnoteEntry objects.

    Args:
        html: Raw HTML for the footnote list.
        current_work: Standard work slug for link resolution.
        book_slug: Book slug owning the footnotes.
        chapter_number: Chapter identifier for the footnotes.
    Returns:
        List of FootnoteEntry objects.
    """

    soup = BeautifulSoup(html, "html.parser")
    entries: List[FootnoteEntry] = []

    def split_segments(li: Tag) -> List[str]:
        """Split a footnote <li> into display-ready segments without touching hrefs."""

        tokens: List[str | Tag] = []
        for child in li.children:
            if isinstance(child, NavigableString):
                parts = re.split(r"(;)", str(child))
                tokens.extend([p for p in parts if p != ""])
            else:
                tokens.append(child)

        segments: List[str] = []
        buffer: List[str] = []
        for idx, tok in enumerate(tokens):
            if tok == ";":
                j = idx + 1
                while (
                    j < len(tokens)
                    and isinstance(tokens[j], str)
                    and tokens[j].strip() == ""
                ):
                    j += 1
                next_tok = tokens[j] if j < len(tokens) else None
                has_alpha = False
                if isinstance(next_tok, str):
                    plain = re.sub(r"<[^>]+>", "", next_tok).strip()
                    has_alpha = bool(re.search(r"[A-Za-z]", plain))
                elif next_tok is not None:
                    text = next_tok.get_text(strip=True)
                    has_alpha = bool(re.search(r"[A-Za-z]", text))
                if has_alpha:
                    buffer.append(";")
                    segments.append("".join(buffer).strip())
                    buffer = []
                else:
                    buffer.append("; ")
            else:
                if isinstance(tok, str):
                    rendered = clean_text(tok)
                else:
                    rendered = _normalize_inline_html(tok)

                plain = re.sub(r"<[^>]+>", "", rendered).strip()
                current = "".join(buffer)
                needs_new_line_for_tg = buffer and re.match(r"TG\b", plain)
                needs_new_line_after_period = (
                    buffer
                    and current.rstrip().endswith(".")
                    and not current.rstrip().endswith(". ")
                    and isinstance(tok, Tag)
                )

                if needs_new_line_for_tg or needs_new_line_after_period:
                    segments.append(current.strip())
                    buffer = [rendered]
                else:
                    buffer.append(rendered)
        if buffer:
            segments.append("".join(buffer).strip())
        return [seg for seg in segments if seg]

    for verse_node in soup.find_all("li", attrs={"data-marker": True}):
        verse = verse_node["data-marker"]
        inner_list = verse_node.find("ul")
        if not inner_list:
            continue
        for li in inner_list.find_all("li", attrs={"data-full-marker": True}):
            letter = li.get("data-marker", "")
            text_markup = _normalize_inline_html(li)
            segments = split_segments(li)
            entry = FootnoteEntry(
                book_slug=book_slug,
                chapter=chapter_number,
                verse=verse,
                letter=letter,
                text=text_markup,
                segments=segments if segments else [text_markup],
                links=_parse_footnote_links(li, current_work),
            )
            entries.append(entry)
    return entries


def _parse_verse(paragraph: dict) -> Verse:
    """Convert a verse paragraph dictionary into a Verse instance.

    Args:
        paragraph: Raw paragraph dictionary for a verse.
    Returns:
        Verse object with normalized HTML and plain text.
    """

    raw_html = paragraph["contentHtml"]
    clean_html = _unwrap_footnote_links(raw_html)
    clean_html = _strip_non_footnote_links(clean_html)
    clean_html = _apply_verse_span_markup(html=clean_html)
    plain = clean_text(BeautifulSoup(clean_html, "html.parser").get_text(" "))
    return Verse(
        chapter="",
        number=paragraph.get("number", ""),
        html=clean_html,
        plain_text=plain,
        compare_id=paragraph.get("compareId", ""),
    )


def _header_blocks(paragraphs: Iterable[dict]) -> List[tuple[str, str]]:
    """Collect header-like paragraph fragments in order."""

    header_types = {"book-title", "chapter-title"}
    return [
        (p["type"], p["contentHtml"]) for p in paragraphs if p["type"] in header_types
    ]


def _standard_work_from_path(path: Path) -> str:
    """Infer the standard work slug from a chapter path."""

    return path.parent.parent.name


def load_chapter(path: Path) -> Chapter:
    """Load a single scraped JSON chapter file into a Chapter object.

    Example:
        >>> _ = load_chapter(Path('external/python-scripture-scraper/_output/en-json/new-testament/matthew/matthew-1.json'))  # doctest: +SKIP
    """

    data = json.loads(path.read_text())
    paragraphs: List[dict] = data["paragraphs"]
    standard_work = _standard_work_from_path(path)
    book_slug = path.parent.name
    chapter_number = data.get("number", path.stem.split("-")[-1])

    verses: List[Verse] = []
    footnotes: List[FootnoteEntry] = []
    for p in paragraphs:
        if p["type"] == "verse":
            verse = _parse_verse(p)
            verse.chapter = chapter_number
            verses.append(verse)
        elif p["type"] == "study-footnotes":
            footnotes.extend(
                _parse_footnotes(
                    p["contentHtml"],
                    current_work=standard_work,
                    book_slug=book_slug,
                    chapter_number=chapter_number,
                )
            )

    title = data.get("name", f"{book_slug} {chapter_number}")
    return Chapter(
        standard_work=standard_work,
        book=book_slug,
        abbrev=data.get("abbrev"),
        number=chapter_number,
        title=title,
        header_blocks=_header_blocks(paragraphs),
        paragraphs=paragraphs,
        verses=verses,
        footnotes=footnotes,
        source_path=path,
    )
