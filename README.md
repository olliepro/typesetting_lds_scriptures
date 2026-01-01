# typesetting_lds_scriptures

Generate a two-column PDF of LDS scripture text with balanced three-column footnotes.

## Quick start

Clone the upstream scraper into `external/`:

```bash
git clone https://github.com/samuelbradshaw/python-scripture-scraper external/python-scripture-scraper
```

```bash
uv run python scripts/build_pdf.py
```

This will:

- Reconfigure and run the upstream [python-scripture-scraper](https://github.com/samuelbradshaw/python-scripture-scraper) with copyrighted study helps enabled.
- Normalize and parse the scraped JSON into typed objects.
- Generate one PDF per standard work in `output/` (for example `book-of-mormon.pdf`), using Palatino, balanced columns, hyphenation, and a pivot-style footnote grid.

To target a specific slice of books instead of the full standard works, pass slugs to `--books` (this overrides `--max-books`):

```bash
uv run python scripts/build_pdf.py --books john alma
```

You can also filter entire standard works with `--works` (e.g., `--works bom nt`) or cap the number of books per work via `--max-books`.

To customize filenames, set a prefix and output directory:

```bash
uv run python scripts/build_pdf.py --output-prefix scriptures --output-dir output
```

The script reads cached JSON from `data/raw/` by default. Use `--redo-scrape` only when you explicitly need a fresh scrape, then adjust scraping options in `scripts/build_pdf.py` by tweaking the `ScrapeConfig` passed to `run_scraper`.
