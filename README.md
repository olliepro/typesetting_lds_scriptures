# typesetting_lds_scriptures

This repository orchestrates scraping the standard works of scripture using [python-scripture-scraper](https://github.com/samuelbradshaw/python-scripture-scraper) and laying them out into a print-friendly PDF with two-column scripture text and three-column footnotes.

## Prerequisites
- Python 3.11+
- System font from TeX Gyre (installed automatically in the container) for a Palatino-compatible appearance.

## Usage

```bash
pip install -r requirements.txt
python scripts/scrape_and_typeset.py --use-sample --limit-chapters 5  # fast demo using upstream sample data
```

To download the full canon (including footnotes and copyrighted study helps) and render it, omit `--use-sample`:

```bash
python scripts/scrape_and_typeset.py --output data/standard-works.pdf --raw data/raw --pause 0.25
```

Use `--test-data` to run the scraper's small test suite of chapters instead of the whole corpus, `--pause` to control the delay between HTTP requests while scraping the live site, and `--limit-chapters` for quick smoke tests while iterating on layout.
