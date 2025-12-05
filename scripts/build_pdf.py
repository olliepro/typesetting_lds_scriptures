"""
End-to-end helper: scrape (optional) and render a sample PDF.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scriptures.ingest import build_corpus
from scriptures.pdf_builder import build_pdf
from scriptures.scraper import ScrapeConfig, run_scraper


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
        "--books",
        nargs="+",
        metavar="SLUG",
        help=(
            "Optional list of book slugs to include (e.g., john alma mosiah). "
            "When provided, overrides --max-books."
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
    return parser.parse_args()


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

    metadata_path = Path("external/python-scripture-scraper/_output/metadata-scriptures.json")
    corpus = build_corpus(raw_root, metadata_path)
    output_pdf = Path("output/scriptures-sample.pdf")
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    build_pdf(
        corpus=corpus,
        output_path=output_pdf,
        max_books=None if args.books else args.max_books,
        metadata=metadata,
        include_books=args.books,
    )


if __name__ == "__main__":
    main()
