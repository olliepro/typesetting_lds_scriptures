"""Inspect layout metrics for Matthew 1 first page (text vs footnotes)."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyphen import Pyphen

from scriptures.ingest import build_corpus
from scriptures.pdf_builder import (
    PageSettings,
    build_styles,
    register_palatino,
    limit_books,
    paginate_book,
)


def main() -> None:
    settings = PageSettings()
    font = register_palatino()
    styles = build_styles(font)
    hyphenator = Pyphen(lang="en_US")

    corpus = build_corpus(
        Path("data/raw"),
        Path("external/python-scripture-scraper/_output/metadata-scriptures.json"),
    )
    # Filter to Matthew only
    nt = next((sw for sw in corpus if sw.slug == "new-testament"), None)
    if not nt:
        print("New Testament not found")
        return
    matthew = next((b for b in nt.books if b.slug == "matthew"), None)
    if not matthew:
        print("Matthew not found")
        return

    slices = paginate_book(matthew, styles, hyphenator, settings)
    if not slices:
        print("No pages produced")
        return
    page1 = slices[0]
    print("Page 1 metrics (Matthew 1):")
    print(f" page size: {settings.page_width:.2f} x {settings.page_height:.2f}")
    print(f" margins: left={settings.margin_left:.2f}, right={settings.margin_right:.2f}, top={settings.margin_top:.2f}, bottom={settings.margin_bottom:.2f}")
    print(f" body_height: {settings.body_height:.2f}")
    print(f" header_height: {page1.header_height:.2f}")
    print(f" text_height: {page1.text_height:.2f}")
    print(f" footnote_height: {page1.footnote_height:.2f}")
    available = settings.body_height - page1.header_height
    print(f" available for text+footnotes: {available:.2f}")
    print(f" whitespace leftover: {available - page1.text_height - page1.footnote_height:.2f}")
    print("--- Text items (first 8) heights ---")
    for itm in page1.text_items[:8]:
        print(f" verse {itm.verse} h={itm.height:.2f}")
    print("--- Header blocks ---")
    for i, blk in enumerate(page1.header_flowables):
        h = blk.wrap(settings.body_width, 10_000)[1]
        print(f" header[{i}] h={h:.2f} before={blk.getSpaceBefore()} after={blk.getSpaceAfter()}")
    print("--- Footnote rows (first 10) ---")
    for (ch, vs, lt, para), h, lines in zip(
        page1.footnote_rows[:10], page1.footnote_row_heights[:10], page1.footnote_row_lines[:10]
    ):
        txt = para.getPlainText() if hasattr(para, "getPlainText") else str(para)
        print(f" ch={ch if ch else ''} vs={vs} lt={lt} h={h:.2f} lines={lines} txt='{txt[:50]}'")


if __name__ == "__main__":
    main()
