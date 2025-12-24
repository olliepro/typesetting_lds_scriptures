"""
End-to-end helper: scrape (optional) and render a sample PDF.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scriptures.ingest import build_corpus
from scriptures.models import StandardWork
from scriptures.pdf_builder import build_pdf
from scriptures.scraper import ScrapeConfig, run_scraper

_WORK_ALIASES = {
    "bom": "book-of-mormon",
    "bofm": "book-of-mormon",
    "dc": "doctrine-and-covenants",
    "d&c": "doctrine-and-covenants",
    "ot": "old-testament",
    "nt": "new-testament",
    "pgp": "pearl-of-great-price",
    "jst": "jst-appendix",
}


def _parse_args() -> argparse.Namespace:
    """Return CLI arguments for the build script."""

    parser = argparse.ArgumentParser(
        description="Build output/scriptures-sample.pdf (optionally skipping scrape)."
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Use existing data/raw instead of scraping fresh content.",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw"),
        help="Directory containing scraped raw data (used when --skip-scrape is set).",
    )
    parser.add_argument(
        "--output-file",
        "-o",
        type=Path,
        default=Path("output/scriptures-sample.pdf"),
        help="File path into which the resulting pdf will be saved.",
    )
    parser.add_argument(
        "--books",
        nargs="+",
        metavar="SLUG",
        help=(
            "Optional list of book slugs to include (e.g., john alma mosiah). "
            "Work aliases (e.g., bom) expand to all books in that work. "
            "When provided, overrides --max-books."
        ),
    )
    parser.add_argument(
        "--works",
        nargs="+",
        metavar="WORK",
        help=(
            "Optional list of standard work slugs or aliases (e.g., bom, ot, nt, dc). "
            "Work entries expand to all books in that work."
        ),
    )
    parser.add_argument(
        "--max-books",
        type=int,
        default=2,
        help=(
            "Limit the number of books per standard work (ignored when --books is used)."
        ),
    )
    parser.add_argument(
        "--max-chapters",
        type=int,
        default=None,
        help="Limit the number of chapters/sections per book.",
    )
    return parser.parse_args()


def _normalize_tokens(tokens: Sequence[str] | None) -> List[str]:
    """Return normalized CLI tokens.

    Args:
        tokens: Sequence of CLI string tokens.
    Returns:
        List of normalized lowercase tokens.
    """

    if not tokens:
        return []
    return [token.strip().lower() for token in tokens if token.strip()]


def _work_slug(token: str) -> str:
    """Return a canonical standard work slug for a token.

    Args:
        token: CLI token representing a work.
    Returns:
        Canonical work slug.
    """

    return _WORK_ALIASES.get(token, token)


def _work_map(*, corpus: Sequence[StandardWork]) -> dict[str, StandardWork]:
    """Return a lookup table of standard works by slug.

    Args:
        corpus: Parsed scripture corpus.
    Returns:
        Mapping of lowercase work slug to StandardWork.
    """

    return {work.slug.lower(): work for work in corpus}


def _expand_work_books(
    *, corpus: Sequence[StandardWork], work_tokens: Sequence[str]
) -> tuple[List[str], set[str]]:
    """Expand work tokens into book slugs.

    Args:
        corpus: Parsed scripture corpus.
        work_tokens: Tokens representing standard works.
    Returns:
        Tuple of (book slugs, missing work slugs).
    """

    work_lookup = _work_map(corpus=corpus)
    books: List[str] = []
    missing: set[str] = set()
    for token in work_tokens:
        slug = _work_slug(token)
        work = work_lookup.get(slug)
        if work is None:
            missing.add(token)
            continue
        books.extend(book.slug for book in work.books)
    return books, missing


def _expand_books_with_works(
    *, corpus: Sequence[StandardWork], book_tokens: Sequence[str]
) -> List[str]:
    """Return book slugs, expanding any work aliases.

    Args:
        corpus: Parsed scripture corpus.
        book_tokens: Tokens representing books or works.
    Returns:
        List of book slugs.
    """

    work_lookup = _work_map(corpus=corpus)
    books: List[str] = []
    for token in book_tokens:
        slug = _work_slug(token)
        work = work_lookup.get(slug)
        if work is None:
            books.append(token)
            continue
        books.extend(book.slug for book in work.books)
    return books


def _unique_ordered(values: Iterable[str]) -> List[str]:
    """Return unique values in original order.

    Args:
        values: Input iterable.
    Returns:
        List of unique values in order.
    """

    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _resolve_include_books(
    *,
    corpus: Sequence[StandardWork],
    book_slugs: Sequence[str] | None,
    work_slugs: Sequence[str] | None,
) -> List[str] | None:
    """Return expanded include list from book/work tokens.

    Args:
        corpus: Parsed scripture corpus.
        book_slugs: Optional list of book or work tokens.
        work_slugs: Optional list of work tokens.
    Returns:
        List of book slugs or None when no filter is applied.

    Example:
        >>> _resolve_include_books(corpus=[], book_slugs=["bom"], work_slugs=None)  # doctest: +SKIP
        ['1-nephi', '2-nephi']
    """

    book_tokens = _normalize_tokens(tokens=book_slugs)
    work_tokens = _normalize_tokens(tokens=work_slugs)
    if not book_tokens and not work_tokens:
        return None
    work_books, missing = _expand_work_books(
        corpus=corpus,
        work_tokens=work_tokens,
    )
    if missing:
        raise AssertionError(f"Unknown work slugs: {', '.join(sorted(missing))}")
    book_books = _expand_books_with_works(
        corpus=corpus,
        book_tokens=book_tokens,
    )
    return _unique_ordered([*work_books, *book_books])


def main() -> None:
    """Render ``output/scriptures-sample.pdf`` using scraped or cached data.

    Example:
        >>> main()  # doctest: +SKIP
    """

    args = _parse_args()
    if args.skip_scrape:
        raw_root = args.raw_root
    else:
        raw_root = run_scraper(ScrapeConfig())

    metadata_path = Path("data/raw/metadata-scriptures.json")
    corpus = build_corpus(
        raw_root=raw_root,
        metadata_path=metadata_path,
        max_chapters=args.max_chapters,
    )
    include_books = _resolve_include_books(
        corpus=corpus,
        book_slugs=args.books,
        work_slugs=args.works,
    )
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    build_pdf(
        corpus=corpus,
        output_path=args.output_file,
        max_books=None if include_books else args.max_books,
        metadata=metadata,
        include_books=include_books,
    )


if __name__ == "__main__":
    main()
