"""
Small, focused text cleaning utilities.
"""

import re
from typing import Callable


_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060]")
_NON_BREAKING_SPACES = re.compile("[\u00a0\u202f]")
_SPACES_AROUND_DASH = re.compile(r"\s*([\u2013\u2014-])\s*")
_HAIR_SPACE = "\u200a"


def normalize_whitespace(value: str) -> str:
    """Collapse unusual whitespace into single ASCII spaces.

    Example:
        >>> normalize_whitespace("a\\u00a0b\\u200bb")
        'a b b'
    """

    clean = _NON_BREAKING_SPACES.sub(" ", value)
    clean = _ZERO_WIDTH.sub("", clean)
    clean = re.sub(r"[ \t\r\f\v]+", " ", clean)
    return clean.strip()


def tighten_dashes(value: str) -> str:
    """Collapse whitespace around en/em dashes and add a hair space afterward.

    Example:
        >>> tighten_dashes("war — peace")
        'war—\u200apeace'
    """

    def replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}{_HAIR_SPACE}"

    return _SPACES_AROUND_DASH.sub(replace, value)


def strip_bracketed_qualifier(value: str) -> str:
    """Remove short bracketed qualifiers that trail a line.

    Qualifiers like \"[heb.]\" or \"[alt.]\" often leak from the HTML parse.
    Only terminal qualifiers of up to six characters are removed.

    Example:
        >>> strip_bracketed_qualifier("word [heb.]")
        'word'
    """

    return re.sub(r"\s*\[[^\]\s]{1,6}\]$", "", value)


def clean_text(value: str) -> str:
    """Run all targeted cleaners in a stable order."""

    cleaners: tuple[Callable[[str], str], ...] = (
        normalize_whitespace,
        tighten_dashes,
        strip_bracketed_qualifier,
    )
    result = value
    for cleaner in cleaners:
        result = cleaner(result)
    return result
