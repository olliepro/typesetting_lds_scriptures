"""
Text helpers for hyphenation and paragraph prep.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

from bs4 import BeautifulSoup
from pyphen import Pyphen

from .cleaning import tighten_dashes


WORD_RE = re.compile(r"[A-Za-z]+")
SOFT_HYPHEN = "\u00ad"


def _positions_from_hyphenated(*, text: str) -> set[int]:
    """Return insertion positions for a hyphenated word string.

    Args:
        text: Word string with hyphen separators.
    Returns:
        Set of 0-based insertion positions in the unhyphenated word.
    """

    positions: set[int] = set()
    idx = 0
    for ch in text:
        if ch == "-":
            positions.add(idx)
        else:
            idx += 1
    return positions


def _hyphenation_positions(
    *, word: str, dic: Pyphen, override: str | None
) -> set[int]:
    """Return merged hyphenation positions for a word.

    Args:
        word: Word to hyphenate.
        dic: Pyphen dictionary.
        override: Optional override string with hyphen separators.
    Returns:
        Set of insertion positions.
    """

    positions = _positions_from_hyphenated(text=dic.inserted(word, hyphen="-"))
    if override:
        positions |= _positions_from_hyphenated(text=override)
    return positions


def _insert_soft_hyphens(*, word: str, positions: Iterable[int]) -> str:
    """Insert soft hyphens into a word at the given positions.

    Args:
        word: Source word.
        positions: Insertion positions within the word.
    Returns:
        Word with soft hyphens inserted.
    """

    slots = sorted({pos for pos in positions if 0 < pos < len(word)}, reverse=True)
    if not slots:
        return word
    chars = list(word)
    for pos in slots:
        chars.insert(pos, SOFT_HYPHEN)
    return "".join(chars)


def _should_hyphenate(*, word: str, override: str | None) -> bool:
    """Return True when the word should be hyphenated.

    Args:
        word: Word to test.
        override: Optional override string.
    Returns:
        True when word length or override warrant hyphenation.
    """

    return len(word) >= 4 or bool(override)


def hyphenate_html(
    html: str,
    dic: Pyphen,
    insert_hair_space: bool = True,
    overrides: Mapping[str, str] | None = None,
) -> str:
    """Insert soft hyphens into long words inside an HTML fragment.

    Args:
        html: HTML fragment to process.
        dic: Pyphen dictionary for baseline hyphenation.
        insert_hair_space: Whether to insert hair spaces after dashes.
        overrides: Optional mapping of words to hyphenated variants.
    Returns:
        HTML string with soft hyphens inserted.

    Example:
        >>> dic = Pyphen(lang='en_US')
        >>> hyphenate_html('everlasting', dic)
        'ev\u00ader\u00adlast\u00ading'
    """

    soup = BeautifulSoup(html, "html.parser")
    for text_node in list(soup.strings):
        source = str(text_node)
        processed = tighten_dashes(source) if insert_hair_space else source

        def repl(match: re.Match[str]) -> str:
            word = match.group(0)
            override = overrides.get(word.lower()) if overrides else None
            if not _should_hyphenate(word=word, override=override):
                return word
            positions = _hyphenation_positions(
                word=word,
                dic=dic,
                override=override,
            )
            return _insert_soft_hyphens(word=word, positions=positions)

        text_node.replace_with(WORD_RE.sub(repl, processed))
    return soup.decode_contents()


def insert_hair_space_html(html: str) -> str:
    """Insert hair spaces after dashes inside an HTML fragment.

    Args:
        html: HTML fragment to process.
    Returns:
        HTML string with hair spaces inserted after dash characters.

    Example:
        >>> insert_hair_space_html("war — peace")
        'war—\u200apeace'
    """

    soup = BeautifulSoup(html, "html.parser")
    for text_node in list(soup.strings):
        text_node.replace_with(tighten_dashes(str(text_node)))
    return soup.decode_contents()
