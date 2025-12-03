from __future__ import annotations

import re
from bs4 import BeautifulSoup

ZERO_WIDTH = ["\u200b", "\u200c", "\u200d", "\ufeff"]


def normalize_whitespace(text: str) -> str:
    for char in ZERO_WIDTH:
        text = text.replace(char, "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\u2028\u2029]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    # Remove noisy qualifiers but preserve semantic elements
    for tag in soup.find_all(True):
        if tag.name in {"span", "div"} and not tag.attrs:
            continue
        if tag.get("class") == ["marker"]:
            tag.name = "sup"
            continue
    return normalize_whitespace(soup.get_text(" "))
