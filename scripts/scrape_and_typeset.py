#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List

from pyphen import Pyphen

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from lds_typesetting.scraping import ScraperConfig, copy_sample, run_scraper
from lds_typesetting.clean import clean_html
from lds_typesetting.layout import Chapter, extract_verses, paginate, render_pdf, default_styles


def load_chapters(raw_path: Path) -> List[Chapter]:
    chapters: List[Chapter] = []
    for work_dir in sorted(raw_path.glob("en-json/*")):
        work = work_dir.name
        for book_dir in sorted(work_dir.iterdir()):
            book = book_dir.name.replace("-", " ")
            for chapter_file in sorted(book_dir.glob("*.json")):
                data = json.loads(chapter_file.read_text())
                chapters.append(extract_verses(data, work, book))
    return chapters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape LDS scriptures and typeset them.")
    parser.add_argument("--output", type=Path, default=Path("data/output.pdf"), help="Path for generated PDF")
    parser.add_argument("--raw", type=Path, default=Path("data/raw"), help="Where scraped content should be written")
    parser.add_argument("--use-sample", action="store_true", help="Use the upstream sample data instead of hitting the network")
    parser.add_argument("--test-data", action="store_true", help="Ask the scraper to use its limited test dataset")
    parser.add_argument("--pause", type=float, default=0.25, help="Seconds to pause between HTTP requests")
    parser.add_argument("--limit-chapters", type=int, default=None, help="Limit how many chapters are processed (useful for quick smoke tests)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.raw.parent.mkdir(parents=True, exist_ok=True)

    if args.use_sample:
        raw_path = copy_sample(args.raw)
    else:
        raw_path = run_scraper(
            args.raw,
            ScraperConfig(
                include_copyrighted=True,
                include_images=True,
                pause_seconds=args.pause,
                use_test_data=args.test_data,
                outputs=("json",),
            ),
        )

    chapters = load_chapters(raw_path)
    if args.limit_chapters:
        chapters = chapters[: args.limit_chapters]
    hyphenator = Pyphen(lang="en_US")
    styles = default_styles(hyphenator)
    pages = paginate(chapters, styles)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(args.output, pages, styles)
    print(f"Wrote PDF to {args.output}")


if __name__ == "__main__":
    main()
