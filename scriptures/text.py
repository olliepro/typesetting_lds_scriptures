"""
Text helpers for hyphenation and paragraph prep.
"""

from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup
from pyphen import Pyphen

from .cleaning import tighten_dashes


WORD_RE = re.compile(r"[A-Za-z]{7,}")


def hyphenate_html(
    html: str, dic: Pyphen, insert_hair_space: bool = True
) -> str:
    """Insert soft hyphens into long words inside an HTML fragment.

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
            return dic.inserted(match.group(0), hyphen="\u00ad")

        text_node.replace_with(WORD_RE.sub(repl, processed))
    return soup.decode_contents()
