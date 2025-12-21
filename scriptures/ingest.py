"""
Helpers that assemble scraped files into typed objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

from .models import Book, StandardWork
from .parser import load_chapter


_CANONICAL_BOOK_ORDER = {
    "old-testament": [
        "genesis",
        "exodus",
        "leviticus",
        "numbers",
        "deuteronomy",
        "joshua",
        "judges",
        "ruth",
        "1-samuel",
        "2-samuel",
        "1-kings",
        "2-kings",
        "1-chronicles",
        "2-chronicles",
        "ezra",
        "nehemiah",
        "esther",
        "job",
        "psalms",
        "proverbs",
        "ecclesiastes",
        "song-of-solomon",
        "isaiah",
        "jeremiah",
        "lamentations",
        "ezekiel",
        "daniel",
        "hosea",
        "joel",
        "amos",
        "obadiah",
        "jonah",
        "micah",
        "nahum",
        "habakkuk",
        "zephaniah",
        "haggai",
        "zechariah",
        "malachi",
    ],
    "new-testament": [
        "matthew",
        "mark",
        "luke",
        "john",
        "acts",
        "romans",
        "1-corinthians",
        "2-corinthians",
        "galatians",
        "ephesians",
        "philippians",
        "colossians",
        "1-thessalonians",
        "2-thessalonians",
        "1-timothy",
        "2-timothy",
        "titus",
        "philemon",
        "hebrews",
        "james",
        "1-peter",
        "2-peter",
        "1-john",
        "2-john",
        "3-john",
        "jude",
        "revelation",
    ],
    "book-of-mormon": [
        "1-nephi",
        "2-nephi",
        "jacob",
        "enos",
        "jarom",
        "omni",
        "words-of-mormon",
        "mosiah",
        "alma",
        "helaman",
        "3-nephi",
        "4-nephi",
        "mormon",
        "ether",
        "moroni",
    ],
    "doctrine-and-covenants": ["sections", "official-declarations"],
    "pearl-of-great-price": [
        "moses",
        "abraham",
        "joseph-smith-matthew",
        "joseph-smith-history",
        "articles-of-faith",
    ],
    "jst-appendix": [
        "jst-genesis",
        "jst-exodus",
        "jst-deuteronomy",
        "jst-1-samuel",
        "jst-2-samuel",
        "jst-1-chronicles",
        "jst-2-chronicles",
        "jst-psalms",
        "jst-isaiah",
        "jst-jeremiah",
        "jst-amos",
        "jst-matthew",
        "jst-mark",
        "jst-luke",
        "jst-john",
        "jst-acts",
        "jst-romans",
        "jst-1-corinthians",
        "jst-2-corinthians",
        "jst-galatians",
        "jst-ephesians",
        "jst-colossians",
        "jst-1-thessalonians",
        "jst-2-thessalonians",
        "jst-1-timothy",
        "jst-1-peter",
        "jst-2-peter",
        "jst-1-john",
        "jst-james",
        "jst-hebrews",
        "jst-revelation",
    ],
}


def load_metadata(path: Path) -> Mapping:
    """Load the scraper-generated metadata-scriptures.json."""

    return json.loads(path.read_text())


def _book_name(meta: Mapping, work_slug: str, book_slug: str) -> str:
    """Return the display name for a book slug.

    Args:
        meta: Metadata payload.
        work_slug: Standard work slug.
        book_slug: Book slug.
    Returns:
        Display name or the slug when metadata is missing.
    """

    return (
        meta.get("structure", {})
        .get(work_slug, {})
        .get("books", {})
        .get(book_slug, {})
        .get("name", book_slug)
    )


def _book_abbrev(meta: Mapping, work_slug: str, book_slug: str) -> str | None:
    """Return the book abbreviation from metadata, if present.

    Args:
        meta: Metadata payload.
        work_slug: Standard work slug.
        book_slug: Book slug.
    Returns:
        Abbreviation or None when unavailable.
    """

    return (
        meta.get("structure", {})
        .get(work_slug, {})
        .get("books", {})
        .get(book_slug, {})
        .get("abbrev")
    )


def _work_name(meta: Mapping, work_slug: str) -> str:
    """Return the display name for a standard work.

    Args:
        meta: Metadata payload.
        work_slug: Standard work slug.
    Returns:
        Display name or slug when metadata is missing.
    """

    return meta.get("structure", {}).get(work_slug, {}).get("name", work_slug)


def _sorted_dirs(*, root: Path) -> List[Path]:
    """Return sorted child directories for a root path.

    Args:
        root: Directory to scan.
    Returns:
        Sorted list of child directories.
    """

    return sorted([path for path in root.iterdir() if path.is_dir()])


def _book_dirs(*, work_dir: Path) -> List[Path]:
    """Return sorted book directories for a work directory.

    Args:
        work_dir: Standard work directory path.
    Returns:
        Sorted list of book directories.
    """

    return _sorted_dirs(root=work_dir)


def _merge_order(*, primary: List[str], fallback: List[str]) -> List[str]:
    """Return a merged order list with unique entries.

    Args:
        primary: Primary ordering list.
        fallback: Fallback ordering list.
    Returns:
        Combined list with duplicates removed.
    """

    seen: set[str] = set()
    merged: List[str] = []
    for slug in [*primary, *fallback]:
        if slug in seen:
            continue
        seen.add(slug)
        merged.append(slug)
    return merged


def _ordered_book_dirs(
    *, work_dir: Path, work_slug: str, meta: Mapping
) -> List[Path]:
    """Return book directories ordered by metadata when available.

    Args:
        work_dir: Standard work directory path.
        work_slug: Standard work slug.
        meta: Metadata payload.
    Returns:
        Ordered list of book directories.
    """

    book_dirs = _book_dirs(work_dir=work_dir)
    meta_order = list(meta.get("structure", {}).get(work_slug, {}).get("books", {}).keys())
    canonical_order = _CANONICAL_BOOK_ORDER.get(work_slug, [])
    primary_order = canonical_order if canonical_order else meta_order
    fallback_order = meta_order if canonical_order else []
    merged_order = _merge_order(primary=primary_order, fallback=fallback_order)
    order_index = {slug: idx for idx, slug in enumerate(merged_order)}
    fallback_base = len(order_index)
    return sorted(
        book_dirs,
        key=lambda path: (order_index.get(path.name, fallback_base), path.name),
    )


def _books_for_work(
    *,
    work_dir: Path,
    work_slug: str,
    meta: Mapping,
    max_chapters: int | None,
) -> List[Book]:
    """Return Book objects for a work directory.

    Args:
        work_dir: Directory containing book subfolders.
        work_slug: Standard work slug.
        meta: Metadata payload.
        max_chapters: Optional cap on chapters per book.
    Returns:
        List of Book objects.
    """

    books: List[Book] = []
    for book_dir in _ordered_book_dirs(
        work_dir=work_dir, work_slug=work_slug, meta=meta
    ):
        book_slug = book_dir.name
        chapter_paths = sorted(book_dir.glob("*.json"), key=_chapter_sort_key)
        chapter_paths = [
            path
            for path in chapter_paths
            if not _skip_abraham_facsimile(book_slug=book_slug, path=path)
        ]
        if max_chapters is not None:
            chapter_paths = chapter_paths[:max_chapters]
        chapters = [load_chapter(path=path) for path in chapter_paths]
        books.append(
            Book(
                standard_work=work_slug,
                name=_book_name(meta, work_slug, book_slug),
                slug=book_slug,
                abbrev=_book_abbrev(meta, work_slug, book_slug),
                chapters=chapters,
            )
        )
    return books


def _skip_abraham_facsimile(*, book_slug: str, path: Path) -> bool:
    """Return True when a chapter path is an Abraham facsimile entry.

    Args:
        book_slug: Book slug for the chapter path.
        path: Chapter JSON path.
    Returns:
        True when the path should be skipped.

    Example:
        >>> _skip_abraham_facsimile(book_slug="abraham", path=Path("abraham-fac-1.json"))
        True
    """

    if book_slug != "abraham":
        return False
    return path.stem.startswith("abraham-fac-")


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


def build_corpus(
    raw_root: Path, metadata_path: Path, max_chapters: int | None = None
) -> List[StandardWork]:
    """Create a typed corpus from a scraped JSON directory.

    Args:
        raw_root: Root folder containing scraped JSON files.
        metadata_path: Path to metadata-scriptures.json.
        max_chapters: Optional cap on chapters/sections per book.
    Returns:
        List of standard works containing books and chapters.

    Example:
        >>> build_corpus(Path('data/raw'), Path('external/python-scripture-scraper/_output/metadata-scriptures.json'))  # doctest: +SKIP
    """

    meta = load_metadata(metadata_path)
    corpus: List[StandardWork] = []
    for work_dir in _sorted_dirs(root=raw_root):
        work_slug = work_dir.name
        books = _books_for_work(
            work_dir=work_dir,
            work_slug=work_slug,
            meta=meta,
            max_chapters=max_chapters,
        )
        if books:
            corpus.append(
                StandardWork(
                    name=_work_name(meta, work_slug),
                    slug=work_slug,
                    books=books,
                )
            )
    return corpus
