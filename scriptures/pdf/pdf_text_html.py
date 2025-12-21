"""HTML parsing and wrapping helpers for scripture text."""

from __future__ import annotations

from typing import Iterable, List, Sequence
import re

from bs4 import BeautifulSoup
from pyphen import Pyphen
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from ..models import Verse
from .pdf_constants import DASH_CHARS, HAIR_SPACE
from ..text import hyphenate_html


def _verse_markup(verse: Verse) -> str:
    """Return HTML markup for a verse with its number.

    Args:
        verse: Verse data object.
    Returns:
        HTML string with the verse number bolded.
    """

    number = verse.number or ""
    html = f"<span>{number}</span> {verse.html}"
    return _italicize_sup_letters(html=html)


SUPERSCRIPT_FONT_SIZE = 8.0


def _sup_font_content(*, text_html: str, italic: bool) -> str:
    """Return superscript content wrapped with a smaller font size.

    Args:
        text_html: Inner HTML for the superscript.
        italic: Whether to wrap the content in italics.
    Returns:
        HTML string for the superscript content.
    """

    content = f"<i>{text_html}</i>" if italic else text_html
    return f'<font size="{SUPERSCRIPT_FONT_SIZE}">{content}</font>'


def _paragraph_from_html(
    *, html: str, style: ParagraphStyle, hyphenator: Pyphen, insert_hair_space: bool
) -> Paragraph:
    """Create a Paragraph with hyphenated text.

    Args:
        html: Raw HTML fragment to wrap.
        style: Paragraph style.
        hyphenator: Hyphenation helper.
        insert_hair_space: Whether to insert hair spaces after hyphenation.
    Returns:
        Paragraph instance with hyphenated HTML.
    """

    normalized = _normalize_breaks(html=html)
    sanitized = _collapse_space_after_sup(_strip_attributes(normalized))
    hyphenated = hyphenate_html(
        sanitized, hyphenator, insert_hair_space=insert_hair_space
    )
    para = Paragraph(hyphenated, style)
    setattr(para, "_orig_html", hyphenated)
    return para


def _line_has_visible_text_after(*, line_html: str, idx: int) -> bool:
    """Return True when non-whitespace content follows the given index.

    Args:
        line_html: HTML string to inspect.
        idx: Character index to start from.
    Returns:
        True if visible content exists after ``idx``.
    """

    cursor = idx + 1
    while cursor < len(line_html):
        ch = line_html[cursor]
        if ch == "<":
            closing = line_html.find(">", cursor + 1)
            if closing == -1:
                break
            cursor = closing + 1
            continue
        if ch.isspace():
            cursor += 1
            continue
        return True
    return False


def _unused_hairspace_positions(
    *, line_htmls: Sequence[str], hyphenated_html: str
) -> List[int]:
    """Return hair space indexes after dashes that still have trailing text.

    Args:
        line_htmls: Wrapped line HTML fragments.
        hyphenated_html: Original hyphenated HTML.
    Returns:
        List of character indexes to remove.
    """

    dash_pairs = _dash_hairspace_pairs(hyphenated_html=hyphenated_html)
    if not dash_pairs:
        return []
    removal: List[int] = []
    pair_idx = 0
    for line_html in line_htmls:
        pair_idx = _collect_removal_positions(
            line_html=line_html,
            dash_pairs=dash_pairs,
            pair_idx=pair_idx,
            removal=removal,
        )
        if pair_idx >= len(dash_pairs):
            break
    return removal


def _dash_hairspace_pairs(*, hyphenated_html: str) -> List[tuple[str, int]]:
    """Return (dash, hair-space-index) pairs from a string.

    Args:
        hyphenated_html: HTML string to scan.
    Returns:
        List of (dash_char, hair_space_index) tuples.
    """

    pairs: List[tuple[str, int]] = []
    for idx in range(len(hyphenated_html) - 1):
        if hyphenated_html[idx] in DASH_CHARS and hyphenated_html[idx + 1] == HAIR_SPACE:
            pairs.append((hyphenated_html[idx], idx + 1))
    return pairs


def _collect_removal_positions(
    *,
    line_html: str,
    dash_pairs: Sequence[tuple[str, int]],
    pair_idx: int,
    removal: List[int],
) -> int:
    """Append removable positions for a line and return next pair index.

    Args:
        line_html: Line HTML to scan.
        dash_pairs: Dash/hair-space pairs from the source.
        pair_idx: Current index in ``dash_pairs``.
        removal: Output list of indexes to remove.
    Returns:
        Updated pair index.
    """

    pos = 0
    while pos < len(line_html) and pair_idx < len(dash_pairs):
        if line_html[pos] == dash_pairs[pair_idx][0]:
            if _line_has_visible_text_after(line_html=line_html, idx=pos):
                removal.append(dash_pairs[pair_idx][1])
            pair_idx += 1
        pos += 1
    return pair_idx


def _strip_characters_at_positions(*, text: str, indexes: Sequence[int]) -> str:
    """Drop characters from ``text`` at the given positions.

    Args:
        text: Source string.
        indexes: Indexes to remove.
    Returns:
        String with characters removed.
    """

    if not indexes:
        return text
    chars = list(text)
    for index in sorted(indexes, reverse=True):
        if 0 <= index < len(chars):
            del chars[index]
    return "".join(chars)


def _wrap_paragraph(
    *, html: str, style: ParagraphStyle, hyphenator: Pyphen, width: float
) -> tuple[Paragraph, List[str]]:
    """Return a paragraph and lines, rewrapping if hair spaces were unused.

    Args:
        html: HTML fragment to wrap.
        style: Paragraph style.
        hyphenator: Hyphenation helper.
        width: Target column width.
    Returns:
        Tuple of (Paragraph, list of line HTML strings).

    Example:
        >>> hyphenator = Pyphen(lang="en_US")
        >>> style = ParagraphStyle("Body")
        >>> _wrap_paragraph(html="<p>test—text</p>", style=style, hyphenator=hyphenator, width=200)
    """

    para = _paragraph_from_html(
        html=html, style=style, hyphenator=hyphenator, insert_hair_space=True
    )
    line_htmls = _line_fragments(para=para, width=width)
    hyphenated_html = getattr(para, "_orig_html", "")
    if hyphenated_html:
        unused_positions = _unused_hairspace_positions(
            line_htmls=line_htmls, hyphenated_html=hyphenated_html
        )
    else:
        unused_positions = []
    if unused_positions:
        cleaned_html = _strip_characters_at_positions(
            text=hyphenated_html, indexes=unused_positions
        )
        para = Paragraph(cleaned_html, style)
        setattr(para, "_orig_html", cleaned_html)
        line_htmls = _line_fragments(para=para, width=width)
    return para, line_htmls


def _ensure_verse_number_span(*, line_html: str, verse_number: str | None) -> str:
    """Keep the verse number wrapped in a span so it survives wrapping.

    Args:
        line_html: Line HTML to inspect.
        verse_number: Verse number to ensure.
    Returns:
        HTML string with verse number wrapped in a span when needed.
    """

    if not verse_number or "<span>" in line_html:
        return line_html
    stripped = line_html.lstrip()
    if not stripped.startswith(verse_number):
        return line_html
    leading = line_html[: len(line_html) - len(stripped)]
    remainder = stripped[len(verse_number) :]
    gap = ""
    if remainder and not remainder[0].isspace() and not remainder.startswith("&nbsp;"):
        gap = " "
    return f"{leading}<span>{verse_number}</span>{gap}{remainder}"


def _strip_attributes(html: str) -> str:
    """Remove non-essential HTML attributes.

    Args:
        html: HTML fragment to sanitize.
    Returns:
        Sanitized HTML string.
    """

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        if tag.name == "a" and tag.has_attr("href"):
            href = tag["href"]
            if isinstance(href, str) and href.startswith("#"):
                tag.unwrap()
                continue
            tag.attrs = {"href": href}
        elif tag.name == "font":
            allowed = {
                k: v for k, v in tag.attrs.items() if k in {"name", "size", "color"}
            }
            tag.attrs = allowed
        else:
            tag.attrs = {}
    text = soup.decode_contents()
    text = re.sub(
        r"(?<=[A-Za-z])(<sup[^>]*>(?:[^<]|<[^>]*>)*</sup>)(?=[A-Za-z])",
        r" \1",
        text,
    )
    return text


def _collapse_space_after_sup(html: str) -> str:
    """Normalize whitespace after <sup> markers.

    Args:
        html: HTML fragment to normalize.
    Returns:
        Normalized HTML string with collapsed whitespace.
    """

    return re.sub(r"</sup>\s+(?=[A-Za-z0-9])", "</sup>", html)


def _apply_hebrew_font(*, html: str, hebrew_font: str | None) -> str:
    """Wrap Hebrew characters with a font tag for a glyph-capable font.

    Args:
        html: Raw HTML string that may contain Hebrew code points.
        hebrew_font: Name of the registered font to apply; when None, the HTML
            is returned unchanged.
    Returns:
        HTML string with Hebrew ranges wrapped in <font name="..."> tags.
    """

    if not hebrew_font:
        return html
    return re.sub(r"([\u0590-\u05FF]+)", rf'<font name="{hebrew_font}">\1</font>', html)


def _italicize_sup_letters(*, html: str) -> str:
    """Wrap single-letter superscripts in italics with smaller size.

    Args:
        html: HTML fragment to process.
    Returns:
        Updated HTML fragment.
    """

    def repl(match: re.Match[str]) -> str:
        inner = match.group(2)
        plain = re.sub(r"<[^>]+>", "", inner)
        if plain and plain.strip().isalpha() and len(plain.strip()) == 1:
            letter = plain.strip()
            sized = _sup_font_content(text_html=letter, italic=True)
            return f"{match.group(1)}{sized}{match.group(3)}"
        return match.group(0)

    return re.sub(r"(<sup[^>]*>)(.*?)(</sup>)", repl, html, flags=re.DOTALL)


def _split_on_breaks(*, html: str) -> List[str]:
    """Split an HTML fragment on <br/> boundaries, preserving empty segments.

    Args:
        html: HTML fragment to split.
    Returns:
        List of HTML segments.
    """

    normalized = _normalize_breaks(html=html)
    return re.split(r"<br\s*/?>", normalized, flags=re.IGNORECASE)


def _normalize_breaks(*, html: str) -> str:
    """Normalize nonstandard line break tags into <br/> tags.

    Args:
        html: HTML fragment to normalize.
    Returns:
        HTML fragment with normalized break tags.
    """

    return re.sub(r"</br\s*>", "<br/>", html, flags=re.IGNORECASE)


def _footnote_letters(*, html: str) -> List[str]:
    """Return lowercase footnote letters found in <sup> tags within HTML.

    Args:
        html: HTML fragment to scan.
    Returns:
        List of footnote letters.
    """

    matches = re.findall(r"<sup[^>]*>(.*?)</sup>", html)
    letters = [re.sub(r"<[^>]+>", "", m) for m in matches]
    return [
        ch.lower()
        for ch in letters
        if ch and ch.strip().isalpha() and len(ch.strip()) == 1
    ]


def _line_fragments(*, para: Paragraph, width: float) -> List[str]:
    """Return a list of HTML strings, one per wrapped line of the paragraph.

    Args:
        para: Paragraph to wrap.
        width: Available width for wrapping.
    Returns:
        List of HTML fragments, one per line.
    """

    setattr(para, "allowOrphans", 1)
    setattr(para, "allowWidows", 1)
    para.wrap(width, 10_000)
    bl_para = getattr(para, "blPara", None)
    if bl_para is None:
        return [para.text]
    base_font = getattr(para.style, "fontName", "")
    lines: List[str] = []
    line_items = getattr(bl_para, "lines", None)
    if line_items is None:
        return [para.text]
    for line in line_items:
        words = _extract_line_words(line=line)
        html_line = _line_html_from_words(words=words, base_font=base_font)
        if not html_line and hasattr(line, "text"):
            html_line = str(getattr(line, "text", "")) or ""
        html_line = _collapse_space_after_sup(html_line)
        lines.append(html_line)
    return lines or [para.text]


def _extract_line_words(*, line: object) -> List[object]:
    """Return the word sequence from a ReportLab line object.

    Args:
        line: Line object from ReportLab paragraph.
    Returns:
        List of word-like objects.
    """

    words_seq = getattr(line, "words", None)
    if words_seq is None:
        words_seq = _fallback_word_sequence(line=line)
    return list(words_seq) if words_seq is not None else []


def _fallback_word_sequence(*, line: object) -> Iterable[object]:
    """Return a fallback iterable of words from a line object.

    Args:
        line: Line object from ReportLab paragraph.
    Returns:
        Iterable of word-like objects.
    """

    if isinstance(line, tuple) and len(line) == 2 and isinstance(line[1], list):
        return line[1]
    if isinstance(line, (list, tuple)) and line:
        candidate = line[0]
        if hasattr(candidate, "__iter__") and not isinstance(candidate, (str, bytes)):
            return candidate
        return line
    return []


def _line_html_from_words(*, words: Sequence[object], base_font: str) -> str:
    """Return HTML for a line based on word fragments.

    Args:
        words: Sequence of word-like objects.
        base_font: Base font name for the paragraph.
    Returns:
        HTML string for the line.
    """

    word_html = [_word_markup(word=w, base_font=base_font) for w in words]
    if all(isinstance(ws, str) and " " not in ws for ws in word_html):
        return " ".join(word_html)
    return "".join(word_html)


def _word_markup(*, word: object, base_font: str) -> str:
    """Return HTML markup for a word fragment.

    Args:
        word: Word-like object from ReportLab.
        base_font: Base font name for the paragraph.
    Returns:
        HTML fragment for the word.
    """

    txt = _word_text(word=word)
    if not txt:
        return ""
    txt = _wrap_anchor(txt=txt, word=word)
    txt = _wrap_bold_italic(txt=txt, word=word)
    txt = _wrap_rise(txt=txt, word=word)
    return _wrap_font(txt=txt, word=word, base_font=base_font)


def _word_text(*, word: object) -> str:
    """Return the base text for a word fragment.

    Args:
        word: Word-like object from ReportLab.
    Returns:
        Text string.
    """

    text_value = getattr(word, "text", None)
    if isinstance(text_value, str):
        return text_value
    if isinstance(word, str):
        return word
    return ""


def _wrap_anchor(*, txt: str, word: object) -> str:
    """Wrap text in an anchor tag when the word has a link.

    Args:
        txt: Word text.
        word: Word-like object.
    Returns:
        HTML string with anchor tag if present.
    """

    hrefs = getattr(word, "link", [])
    if not hrefs:
        return txt
    href = hrefs[0][1]
    return f'<a href="{href}">{txt}</a>'


def _wrap_bold_italic(*, txt: str, word: object) -> str:
    """Wrap text in bold/italic tags based on word styling.

    Args:
        txt: Word text.
        word: Word-like object.
    Returns:
        HTML string with bold/italic tags.
    """

    font_name = getattr(word, "fontName", "")
    if "Bold" in font_name or getattr(word, "bold", 0):
        txt = f"<b>{txt}</b>"
    if "Italic" in font_name or "Oblique" in font_name or getattr(word, "italic", 0):
        txt = f"<i>{txt}</i>"
    return txt


def _wrap_rise(*, txt: str, word: object) -> str:
    """Wrap text in super/subscript tags based on rise.

    Args:
        txt: Word text.
        word: Word-like object.
    Returns:
        HTML string with sup/sub tags if needed.
    """

    rise = getattr(word, "rise", 0)
    plain = re.sub(r"<[^>]+>", "", txt)
    if rise > 0:
        if plain and plain.strip().isalpha() and len(plain.strip()) == 1:
            sized = _sup_font_content(text_html=plain.strip(), italic=True)
            return f"<sup>{sized}</sup>"
        return f"<sup>{txt}</sup>"
    if rise < 0:
        return f"<sub>{txt}</sub>"
    return txt


def _wrap_font(*, txt: str, word: object, base_font: str) -> str:
    """Wrap text in a font tag when it uses a non-base font.

    Args:
        txt: Word text.
        word: Word-like object.
        base_font: Base font name.
    Returns:
        HTML string with font tag when required.
    """

    font_name = getattr(word, "fontName", "")
    if not font_name or font_name == base_font:
        return txt
    if font_name in _font_family_variants(base_font=base_font):
        return txt
    return f'<font name="{font_name}">{txt}</font>'


def _font_family_variants(*, base_font: str) -> set[str]:
    """Return common family variant names for a base font.

    Args:
        base_font: Base family name.
    Returns:
        Set of variant font names.
    """

    return {
        base_font,
        f"{base_font}-Bold",
        f"{base_font}-Italic",
        f"{base_font}-BoldItalic",
    }
