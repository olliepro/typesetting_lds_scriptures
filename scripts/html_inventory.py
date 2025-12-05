"""Utilities to tally HTML tags and classes in scraped chapter content.

Run directly to print counts:
    uv run python scripts/html_inventory.py --root external/python-scripture-scraper/_output/en-json
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

import json
from bs4 import BeautifulSoup


@dataclass(slots=True)
class HtmlInventory:
    """Aggregated counts of tags and classes.

    Attributes:
        tag_counts: occurrences keyed by tag name.
        class_counts: occurrences keyed by individual class name.
        tag_class_counts: occurrences keyed by (tag, class) pairs.

    Example:
        >>> inv = HtmlInventory(Counter({"p": 2}), Counter({"verse": 1}), Counter({("p", "verse"): 1}))
        >>> inv.tag_counts["p"]
        2
    """

    tag_counts: Counter[str]
    class_counts: Counter[str]
    tag_class_counts: Counter[Tuple[str, str]]


def collect_html_inventory(root: Path) -> HtmlInventory:
    """Walk JSON chapter files under ``root`` and tally HTML tags/classes.

    Args:
        root: Directory containing chapter JSON files (split by chapter).

    Returns:
        HtmlInventory with counters populated from all ``contentHtml`` values.
    """

    assert root.exists(), f"Missing data directory: {root}"
    tag_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    tag_class_counts: Counter[Tuple[str, str]] = Counter()

    for path in root.rglob("*.json"):
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        paragraphs: Iterable[dict] = data.get("paragraphs", []) if isinstance(data, dict) else []
        for para in paragraphs:
            html = para.get("contentHtml")
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for el in soup.find_all(True):
                tag_counts[el.name] += 1
                for cls in el.get("class", []):
                    class_counts[cls] += 1
                    tag_class_counts[(el.name, cls)] += 1

    return HtmlInventory(tag_counts=tag_counts, class_counts=class_counts, tag_class_counts=tag_class_counts)


def _top(counter: Counter, limit: int = 25):
    """Return the most common items up to ``limit`` entries."""

    return counter.most_common(limit)


def main(
    root: str = "external/python-scripture-scraper/_output/en-json",
    limit: int = 25,
    pair_limit: int = 100,
) -> None:
    """Print tag/class frequency tables for the scraped chapters.

    Args:
        root: Base directory containing chapter JSON files.
        limit: Number of tag and class rows to display.
        pair_limit: Number of tag/class pair rows to display.
    """

    inventory = collect_html_inventory(Path(root))

    def fmt(title: str, items):
        print(f"\n{title} (top {len(items)}):")
        for key, count in items:
            print(f"  {key}: {count}")

    fmt("Tags", _top(inventory.tag_counts, limit))
    fmt("Classes", _top(inventory.class_counts, limit))
    fmt("Tag/Class pairs", _top(inventory.tag_class_counts, pair_limit))


if __name__ == "__main__":
    main()
