# typesetting_lds_scriptures

Generate a two-column PDF of LDS scripture text with balanced three-column footnotes.

## Quick start

```bash
uv run python scripts/build_pdf.py
```

This will:

- Reconfigure and run the upstream [python-scripture-scraper](https://github.com/samuelbradshaw/python-scripture-scraper) against its bundled test set (two books per standard work) with copyrighted study helps enabled.
- Normalize and parse the scraped JSON into typed objects.
- Lay out the subset into `output/scriptures-sample.pdf` using Palatino, balanced columns, hyphenation, and a pivot-style footnote grid.

To target a specific slice of books instead of the default two per standard work, pass slugs to `--books` (this also disables the per-work cap):

```bash
uv run python scripts/build_pdf.py --skip-scrape --books john alma
```

Adjust the sample cap with `--max-books` (e.g., `--max-books 5`) when you want more of each standard work without enumerating every book.

The script caches scraped JSON in `data/raw/`. Adjust scraping options in `scripts/build_pdf.py` by tweaking the `ScrapeConfig` passed to `run_scraper`.
