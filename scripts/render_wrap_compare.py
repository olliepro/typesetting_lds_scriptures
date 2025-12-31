"""
Render a verse with original and recombined wraps into a PDF.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from pyphen import Pyphen
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import BaseDocTemplate, Frame, Paragraph, Spacer, XPreformatted
from reportlab.platypus.doctemplate import PageTemplate

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scriptures.ingest import build_corpus
from scriptures.models import Chapter, StandardWork, Verse
from scriptures.pdf.pdf_settings import PageSettings, build_styles, register_palatino
from scriptures.pdf.pdf_text import _line_fragments, _split_on_breaks, _verse_markup
from scriptures.pdf.pdf_text_html import _wrap_paragraph


@dataclass(slots=True)
class VerseRef:
    """Reference to a verse location.

    Args:
        work_slug: Standard work slug.
        book_slug: Book slug.
        chapter: Chapter identifier.
        verse: Verse number.
    """

    work_slug: str
    book_slug: str
    chapter: str
    verse: str

    def label(self) -> str:
        """Return a display label for the verse.

        Returns:
            Label string such as "alma 5:14".
        """

        return f"{self.book_slug} {self.chapter}:{self.verse}"


@dataclass(slots=True)
class RenderContext:
    """Shared render state for wrap comparison.

    Args:
        settings: Page settings with fonts applied.
        styles: Paragraph styles for rendering.
        hyphenator: Hyphenation helper.
        column_width: Column width for wrapping.
        line_style: Style used for rendering line HTML.
        heading_style: Style used for section headings.
        title_style: Style used for title headings.
    """

    settings: PageSettings
    styles: dict[str, ParagraphStyle]
    hyphenator: Pyphen
    column_width: float
    line_style: ParagraphStyle
    heading_style: ParagraphStyle
    title_style: ParagraphStyle


@dataclass(slots=True)
class WrapComparison:
    """Line wrap comparison for a verse segment.

    Args:
        segment_index: Segment index within the verse.
        original_lines: Lines from the initial wrap.
        recombined_lines: Lines after recombination and rewrap.
    """

    segment_index: int
    original_lines: list[str]
    recombined_lines: list[str]


def _parse_args() -> argparse.Namespace:
    """Return CLI arguments for the render helper.

    Returns:
        Parsed argparse.Namespace.
    """

    parser = argparse.ArgumentParser(
        description="Render a verse with original and recombined wraps."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/alma-5-14-wrap-compare.pdf"),
        help="Output PDF file path.",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw"),
        help="Directory containing scraped JSON data.",
    )
    parser.add_argument(
        "--metadata-path",
        type=Path,
        default=Path("data/raw/metadata-scriptures.json"),
        help="Path to metadata-scriptures.json.",
    )
    parser.add_argument(
        "--work",
        default="book-of-mormon",
        help="Standard work slug (default: book-of-mormon).",
    )
    parser.add_argument(
        "--book",
        default="alma",
        help="Book slug (default: alma).",
    )
    parser.add_argument(
        "--chapter",
        default="5",
        help="Chapter identifier (default: 5).",
    )
    parser.add_argument(
        "--verse",
        default="14",
        help="Verse number (default: 14).",
    )
    return parser.parse_args()


def _build_context() -> RenderContext:
    """Return configured render context with fonts and styles.

    Returns:
        RenderContext with fonts, styles, and column width.

    Example:
        >>> ctx = _build_context()
        >>> ctx.column_width > 0
        True
    """

    settings = PageSettings()
    font_name = register_palatino()
    settings.font_name = font_name
    settings.font_bold_name = "Palatino-Bold"
    styles = build_styles(font_name)
    column_width = settings.text_column_width() - settings.column_gap / 2
    line_style = ParagraphStyle(
        "WrapLine",
        parent=styles["body"],
        alignment=TA_LEFT,
        firstLineIndent=0,
    )
    heading_style = ParagraphStyle(
        "WrapHeading",
        parent=styles["body"],
        fontSize=12,
        leading=14,
        spaceBefore=8,
        spaceAfter=4,
        alignment=TA_LEFT,
        firstLineIndent=0,
    )
    title_style = ParagraphStyle(
        "WrapTitle",
        parent=getSampleStyleSheet()["Heading2"],
        fontName=font_name,
        fontSize=14,
        leading=18,
        spaceAfter=8,
        alignment=TA_LEFT,
    )
    return RenderContext(
        settings=settings,
        styles=styles,
        hyphenator=Pyphen(lang="en_US"),
        column_width=column_width,
        line_style=line_style,
        heading_style=heading_style,
        title_style=title_style,
    )


def _iter_chapters(
    *, corpus: Sequence[StandardWork]
) -> Iterable[tuple[str, Chapter]]:
    """Yield (book_slug, chapter) pairs from the corpus.

    Args:
        corpus: Standard works to scan.
    Returns:
        Iterable of (book_slug, Chapter).
    """

    for work in corpus:
        for book in work.books:
            for chapter in book.chapters:
                yield book.slug, chapter


def _find_verse(*, corpus: Sequence[StandardWork], ref: VerseRef) -> Verse:
    """Return the Verse matching the reference.

    Args:
        corpus: Standard works to scan.
        ref: Verse reference details.
    Returns:
        Verse instance for the requested reference.
    """

    for book_slug, chapter in _iter_chapters(corpus=corpus):
        if (
            chapter.standard_work != ref.work_slug
            or book_slug != ref.book_slug
            or chapter.number != ref.chapter
        ):
            continue
        for verse in chapter.verses:
            if verse.number == ref.verse:
                return verse
    raise AssertionError(f"Verse not found: {ref.label()}")


def _wrap_segment(*, html: str, context: RenderContext) -> list[str]:
    """Return wrapped lines for a verse segment.

    Args:
        html: Segment HTML to wrap.
        context: Render context with styles and widths.
    Returns:
        List of wrapped line HTML strings.
    """

    _, line_htmls = _wrap_paragraph(
        html=html,
        style=context.styles["body"],
        hyphenator=context.hyphenator,
        width=context.column_width,
    )
    return line_htmls


def _recombine_lines(*, lines: Sequence[str]) -> str:
    """Return recombined HTML from wrapped line fragments.

    Args:
        lines: Wrapped line HTML fragments.
    Returns:
        Recombined HTML string.
    """

    return " ".join(lines)


def _rewrap_recombined(*, html: str, context: RenderContext) -> list[str]:
    """Return wrapped lines after recombining line HTML.

    Args:
        html: Recombined HTML string.
        context: Render context with styles and widths.
    Returns:
        List of wrapped line HTML strings.
    """

    paragraph = Paragraph(html, context.styles["body"])
    return _line_fragments(para=paragraph, width=context.column_width)


def _wrap_comparisons(*, verse: Verse, context: RenderContext) -> list[WrapComparison]:
    """Return wrap comparisons for each verse segment.

    Args:
        verse: Verse to render.
        context: Render context with styles and widths.
    Returns:
        List of WrapComparison entries.
    """

    verse_html = _verse_markup(verse)
    segments = _split_on_breaks(html=verse_html)
    comparisons: list[WrapComparison] = []
    for idx, segment_html in enumerate(segments):
        if not segment_html.strip():
            continue
        original_lines = _wrap_segment(html=segment_html, context=context)
        recombined_html = _recombine_lines(lines=original_lines)
        recombined_lines = _rewrap_recombined(
            html=recombined_html,
            context=context,
        )
        comparisons.append(
            WrapComparison(
                segment_index=idx,
                original_lines=original_lines,
                recombined_lines=recombined_lines,
            )
        )
    return comparisons


def _lines_block(
    *, lines: Sequence[str], context: RenderContext
) -> XPreformatted:
    """Return a preformatted block for line rendering.

    Args:
        lines: Line HTML strings to render.
        context: Render context with line style.
    Returns:
        XPreformatted block preserving line breaks.
    """

    text = "\n".join(lines)
    return XPreformatted(text, context.line_style)


def _segment_heading(*, index: int, context: RenderContext) -> Paragraph:
    """Return a heading Paragraph for a segment.

    Args:
        index: Segment index.
        context: Render context with heading style.
    Returns:
        Paragraph heading for the segment.
    """

    return Paragraph(f"Segment {index + 1}", context.heading_style)


def _render_story(
    *,
    comparisons: Sequence[WrapComparison],
    ref: VerseRef,
    context: RenderContext,
) -> list:
    """Return a story list for the wrap comparison PDF.

    Args:
        comparisons: WrapComparison entries to render.
        ref: Verse reference for headings.
        context: Render context with styles.
    Returns:
        List of flowables for the PDF story.
    """

    story: list = [Paragraph(f"Wrap comparison: {ref.label()}", context.title_style)]
    for comparison in comparisons:
        story.append(_segment_heading(index=comparison.segment_index, context=context))
        story.append(Paragraph("Original wrap", context.heading_style))
        story.append(
            _lines_block(lines=comparison.original_lines, context=context)
        )
        story.append(Spacer(1, context.line_style.leading or 12))
        story.append(Paragraph("Recombined wrap", context.heading_style))
        story.append(
            _lines_block(lines=comparison.recombined_lines, context=context)
        )
        story.append(Spacer(1, (context.line_style.leading or 12) * 1.5))
    return story


def _doc_template(*, output_path: Path, context: RenderContext) -> BaseDocTemplate:
    """Return a BaseDocTemplate with a single column frame.

    Args:
        output_path: Output PDF path.
        context: Render context with page settings.
    Returns:
        Configured BaseDocTemplate.
    """

    page_width = context.settings.page_width
    page_height = context.settings.page_height
    margin = 36
    right_margin = page_width - margin - context.column_width
    assert right_margin >= 0, "Column width exceeds page width."
    frame = Frame(
        margin,
        margin,
        context.column_width,
        page_height - 2 * margin,
        showBoundary=0,
    )
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=(page_width, page_height),
        leftMargin=margin,
        rightMargin=right_margin,
        topMargin=margin,
        bottomMargin=margin,
    )
    doc.addPageTemplates([PageTemplate(id="wrap-compare", frames=[frame])])
    return doc


def build_wrap_compare_pdf(
    *,
    output_path: Path,
    verse: Verse,
    ref: VerseRef,
    context: RenderContext,
) -> Path:
    """Render a PDF comparing original and recombined wraps.

    Args:
        output_path: Path to the output PDF.
        verse: Verse to render.
        ref: Verse reference metadata.
        context: Render context with styles and widths.
    Returns:
        Path to the generated PDF.
    """

    comparisons = _wrap_comparisons(verse=verse, context=context)
    story = _render_story(comparisons=comparisons, ref=ref, context=context)
    doc = _doc_template(output_path=output_path, context=context)
    doc.build(story)
    return output_path


def main() -> None:
    """Render a wrap comparison PDF for a verse.

    Example:
        >>> main()  # doctest: +SKIP
    """

    args = _parse_args()
    assert args.metadata_path.exists(), "metadata-scriptures.json is required"
    ref = VerseRef(
        work_slug=args.work,
        book_slug=args.book,
        chapter=str(args.chapter),
        verse=str(args.verse),
    )
    corpus = build_corpus(
        raw_root=args.raw_root,
        metadata_path=args.metadata_path,
        max_chapters=None,
    )
    context = _build_context()
    verse = _find_verse(corpus=corpus, ref=ref)
    output_path = build_wrap_compare_pdf(
        output_path=args.output,
        verse=verse,
        ref=ref,
        context=context,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
