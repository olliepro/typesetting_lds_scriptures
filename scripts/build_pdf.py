"""
End-to-end helper: scrape (optional) and render per-work PDFs.
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
from scriptures.pdf_builder import build_pdfs_by_work, select_books
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
_EXCLUDED_WORK_SLUGS = {"jst-appendix"}


def _parse_args() -> argparse.Namespace:
    """Return CLI arguments for the build script."""

    parser = argparse.ArgumentParser(
        description="Build per-work PDFs in output/ (uses cached data/raw by default)."
    )
    parser.add_argument(
        "--redo-scrape",
        action="store_true",
        help=(
            "DANGEROUS: re-scrape upstream content and overwrite data/raw. "
            "DO NOT USE unless you explicitly need a fresh scrape."
        ),
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw"),
        help="Directory containing scraped raw data (and destination for --redo-scrape).",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("output"),
        help="Directory where per-work PDFs will be written.",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default="",
        help=(
            "Optional filename prefix for each PDF (e.g., scriptures). "
            "When omitted, filenames are '<work>.pdf'."
        ),
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
        default=None,
        help=(
            "Limit the number of books per standard work (ignored when --books is used). "
            "Defaults to all books."
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


def _normalize_output_prefix(prefix: str | None) -> str | None:
    """Return a cleaned output prefix or None when empty.

    Args:
        prefix: Optional prefix string for output filenames.
    Returns:
        Cleaned prefix or None when not provided.
    """

    if not prefix:
        return None
    cleaned = prefix.strip().strip("-")
    return cleaned or None


def _metadata_path(*, raw_root: Path) -> Path:
    """Return the metadata path under the raw root.

    Args:
        raw_root: Root directory containing scraped JSON.
    Returns:
        Path to metadata-scriptures.json under ``raw_root``.
    """

    return raw_root / "metadata-scriptures.json"


def _warn_redo_scrape(*, raw_root: Path) -> None:
    """Print a warning about re-scraping upstream content.

    Args:
        raw_root: Destination directory that will be overwritten.
    Returns:
        None.
    """

    banner = "!" * 78
    message = (
        f"{banner}\n"
        "WARNING: --redo-scrape will re-scrape upstream content and overwrite\n"
        f"{raw_root}.\n"
        "DO NOT USE THIS for normal PDF builds. Only use it when you\n"
        "explicitly need a fresh scrape.\n"
        f"{banner}"
    )
    print(message, file=sys.stderr)


def _resolve_raw_root(*, args: argparse.Namespace) -> Path:
    """Return the raw data root, running the scraper when requested.

    Args:
        args: Parsed CLI arguments.
    Returns:
        Path to the raw data directory.
    """

    if not args.redo_scrape:
        return args.raw_root
    _warn_redo_scrape(raw_root=args.raw_root)
    return run_scraper(cfg=ScrapeConfig(), dest_root=args.raw_root)


def _load_corpus(
    *, raw_root: Path, max_chapters: int | None
) -> tuple[List[StandardWork], Path]:
    """Load the scripture corpus and resolve metadata path.

    Args:
        raw_root: Root directory containing scraped JSON.
        max_chapters: Optional cap on chapters per book.
    Returns:
        Tuple of (corpus, metadata path).
    """

    metadata_path = _metadata_path(raw_root=raw_root)
    corpus = build_corpus(
        raw_root=raw_root,
        metadata_path=metadata_path,
        max_chapters=max_chapters,
    )
    return corpus, metadata_path


def _filter_corpus(
    *,
    corpus: Sequence[StandardWork],
    book_tokens: Sequence[str] | None,
    work_tokens: Sequence[str] | None,
    max_books: int | None,
) -> tuple[List[StandardWork], int | None]:
    """Return a filtered corpus and resolved max_books value.

    Args:
        corpus: Parsed scripture corpus.
        book_tokens: Optional list of book or work tokens.
        work_tokens: Optional list of standard work tokens.
        max_books: Optional per-work book cap.
    Returns:
        Tuple of (filtered corpus, resolved max_books).
    """

    excluded_book_slugs = _book_slugs_for_works(
        corpus=corpus, work_slugs=_EXCLUDED_WORK_SLUGS
    )
    filtered_books = _filter_tokens_for_excluded_works(
        tokens=book_tokens,
        excluded_slugs=_EXCLUDED_WORK_SLUGS,
        excluded_book_slugs=excluded_book_slugs,
    )
    filtered_works = _filter_tokens_for_excluded_works(
        tokens=work_tokens,
        excluded_slugs=_EXCLUDED_WORK_SLUGS,
        excluded_book_slugs=excluded_book_slugs,
    )
    include_books = _resolve_include_books(
        corpus=corpus,
        book_slugs=filtered_books,
        work_slugs=filtered_works,
    )
    trimmed_corpus = _exclude_works(
        corpus=corpus, excluded_slugs=sorted(_EXCLUDED_WORK_SLUGS)
    )
    if include_books:
        return (
            select_books(
                corpus=trimmed_corpus,
                book_slugs=include_books,
                max_books=None,
            ),
            None,
        )
    return trimmed_corpus, max_books


def _load_metadata(*, metadata_path: Path) -> dict:
    """Load scraper metadata as a dictionary.

    Args:
        metadata_path: Path to metadata-scriptures.json.
    Returns:
        Parsed metadata dictionary or empty dict when missing.
    """

    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text())


def _render_pdfs(
    *,
    corpus: Sequence[StandardWork],
    metadata_path: Path,
    output_dir: Path,
    output_prefix: str | None,
    max_books: int | None,
) -> None:
    """Render per-work PDFs to disk.

    Args:
        corpus: Scripture corpus to render.
        metadata_path: Path to scraper metadata JSON.
        output_dir: Directory for output PDFs.
        output_prefix: Optional filename prefix for each work PDF.
        max_books: Optional per-work book cap.
    Returns:
        None.
    """

    resolved_prefix = _normalize_output_prefix(prefix=output_prefix)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = _load_metadata(metadata_path=metadata_path)
    build_pdfs_by_work(
        corpus=corpus,
        output_dir=output_dir,
        output_prefix=resolved_prefix,
        max_books=max_books,
        metadata=metadata,
    )


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


def _book_slugs_for_works(
    *, corpus: Sequence[StandardWork], work_slugs: Sequence[str]
) -> set[str]:
    """Return book slugs for the selected standard works.

    Args:
        corpus: Parsed scripture corpus.
        work_slugs: Standard work slugs to scan.
    Returns:
        Set of book slugs for the requested works.
    """

    wanted = {slug.lower() for slug in work_slugs}
    return {
        book.slug
        for work in corpus
        if work.slug in wanted
        for book in work.books
    }


def _filter_tokens_for_excluded_works(
    *,
    tokens: Sequence[str] | None,
    excluded_slugs: set[str],
    excluded_book_slugs: set[str],
) -> List[str] | None:
    """Return tokens with excluded works and books removed.

    Args:
        tokens: Input tokens for books or works.
        excluded_slugs: Work slugs to exclude.
        excluded_book_slugs: Book slugs to exclude.
    Returns:
        Filtered token list, or None when empty.
    """

    if not tokens:
        return None
    filtered: List[str] = []
    for token in _normalize_tokens(tokens=tokens):
        slug = _work_slug(token)
        if slug in excluded_slugs or token in excluded_book_slugs:
            continue
        filtered.append(token)
    return filtered or None


def _exclude_works(
    *, corpus: Sequence[StandardWork], excluded_slugs: Sequence[str]
) -> List[StandardWork]:
    """Return a corpus without excluded standard works.

    Args:
        corpus: Parsed scripture corpus.
        excluded_slugs: Slugs of works to exclude.
    Returns:
        Filtered corpus list.

    Example:
        >>> _exclude_works(corpus=[], excluded_slugs=["jst-appendix"])
        []
    """

    excluded = {slug.lower() for slug in excluded_slugs}
    return [work for work in corpus if work.slug not in excluded]


def main() -> None:
    """Render per-work PDFs using scraped or cached data.

    Example:
        >>> main()  # doctest: +SKIP
    """

    args = _parse_args()
    raw_root = _resolve_raw_root(args=args)
    corpus, metadata_path = _load_corpus(
        raw_root=raw_root,
        max_chapters=args.max_chapters,
    )
    corpus, max_books = _filter_corpus(
        corpus=corpus,
        book_tokens=args.books,
        work_tokens=args.works,
        max_books=args.max_books,
    )
    _render_pdfs(
        corpus=corpus,
        metadata_path=metadata_path,
        output_dir=args.output_dir,
        output_prefix=args.output_prefix,
        max_books=max_books,
    )


if __name__ == "__main__":
    main()
