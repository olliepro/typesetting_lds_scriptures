"""
Helpers that assemble scraped files into typed objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

from .models import Book, StandardWork
from .parser import load_chapter


def load_metadata(path: Path) -> Mapping:
    """Load the scraper-generated metadata-scriptures.json."""

    return json.loads(path.read_text())


def _book_name(meta: Mapping, work_slug: str, book_slug: str) -> str:
    return meta.get("structure", {}).get(work_slug, {}).get("books", {}).get(book_slug, {}).get("name", book_slug)


def _book_abbrev(meta: Mapping, work_slug: str, book_slug: str) -> str | None:
    return meta.get("structure", {}).get(work_slug, {}).get("books", {}).get(book_slug, {}).get("abbrev")


def _work_name(meta: Mapping, work_slug: str) -> str:
    return meta.get("structure", {}).get(work_slug, {}).get("name", work_slug)


def _chapter_sort_key(path: Path) -> Tuple[int, int | str]:
    """Return a sortable key that respects numeric chapter ordering."""

    stem = path.stem
    # Handle filenames like "1-corinthians-16" or "section-102".
    last_part = stem.split("-")[-1]
    try:
        num = int(last_part)
        return (0, num)
    except ValueError:
        return (1, stem)


def build_corpus(raw_root: Path, metadata_path: Path) -> List[StandardWork]:
    """Create a typed corpus from a scraped JSON directory.

    Example:
        >>> build_corpus(Path('data/raw'), Path('external/python-scripture-scraper/_output/metadata-scriptures.json'))  # doctest: +SKIP
    """

    meta = load_metadata(metadata_path)
    corpus: List[StandardWork] = []
    for work_slug, work_meta in meta.get("structure", {}).items():
        work_dir = raw_root / work_slug
        if not work_dir.exists():
            continue
        books: List[Book] = []
        for book_slug in work_meta.get("books", {}):
            book_dir = work_dir / book_slug
            if not book_dir.exists():
                continue
            chapter_paths = sorted(book_dir.glob("*.json"), key=_chapter_sort_key)
            chapters = [load_chapter(path) for path in chapter_paths]
            books.append(
                Book(
                    standard_work=work_slug,
                    name=_book_name(meta, work_slug, book_slug),
                    slug=book_slug,
                    abbrev=_book_abbrev(meta, work_slug, book_slug),
                    chapters=chapters,
                )
            )
        if books:
            corpus.append(StandardWork(name=_work_name(meta, work_slug), slug=work_slug, books=books))
    return corpus
