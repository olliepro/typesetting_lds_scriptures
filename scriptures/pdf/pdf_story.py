"""Story and template assembly for PDF output."""

from __future__ import annotations

from typing import Dict, List, Sequence

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)

from .pdf_columns import _text_table
from .pdf_footnotes import _footnote_table
from .pdf_settings import PageSettings
from .pdf_types import PageSlice
from ..models import StandardWork


def _toc_flowables(
    *,
    corpus: Sequence[StandardWork],
    chapter_pages: dict[tuple[str, str], int],
    styles: Dict[str, ParagraphStyle],
) -> List[Paragraph]:
    """Build simple table of contents paragraphs.

    Args:
        corpus: Standard works to include.
        chapter_pages: Mapping of (book_slug, chapter) to page numbers.
        styles: Paragraph styles.
    Returns:
        List of TOC Paragraphs.
    """

    entries: List[Paragraph] = [Paragraph("<b>Contents</b>", styles["header"])]
    for work in corpus:
        entries.append(Paragraph(work.name, styles["preface"]))
        for book in work.books:
            for chapter in book.chapters:
                page = chapter_pages.get((book.slug, chapter.number))
                if not page:
                    continue
                label = f"{book.name} {chapter.number}"
                entries.append(Paragraph(f"{label} ... {page}", styles["body"]))
    return entries


def _on_page_factory(*, label: str, font_name: str, settings: PageSettings):
    """Create an onPage callback that renders page number and range.

    Args:
        label: Page range label.
        font_name: Font name for page numbers.
        settings: Page settings.
    Returns:
        onPage callback function.
    """

    def draw(canvas, doc):
        canvas.saveState()
        canvas.bookmarkPage(f"page-{doc.page}")
        canvas.setFont(font_name, 9)
        y = settings.page_height - settings.margin_top + 8
        canvas.drawString(settings.margin_left, y, str(doc.page))
        canvas.drawRightString(settings.page_width - settings.margin_right, y, label)
        canvas.restoreState()

    return draw


def _page_templates(
    *, page_slices: Sequence[PageSlice], settings: PageSettings, font_name: str
) -> List[PageTemplate]:
    """Build PageTemplate objects for TOC and content pages.

    Args:
        page_slices: Pages to render.
        settings: Page settings.
        font_name: Font name for page numbers.
    Returns:
        List of PageTemplate objects.
    """

    templates: List[PageTemplate] = []
    #     _toc_template(settings=settings, font_name=font_name)
    # ]
    for slice_ in page_slices:
        templates.append(
            _content_template(slice_=slice_, settings=settings, font_name=font_name)
        )
    return templates


def _toc_template(*, settings: PageSettings, font_name: str) -> PageTemplate:
    """Return the TOC page template.

    Args:
        settings: Page settings.
        font_name: Font name for page numbers.
    Returns:
        PageTemplate for the table of contents.
    """

    toc_frame = Frame(
        settings.margin_left,
        settings.margin_bottom,
        settings.body_width,
        settings.body_height,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="toc-frame",
    )
    return PageTemplate(
        id="toc",
        frames=[toc_frame],
        onPage=_on_page_factory(
            label="Contents", font_name=font_name, settings=settings
        ),
    )


def _content_template(
    *, slice_: PageSlice, settings: PageSettings, font_name: str
) -> PageTemplate:
    """Return a content page template for a PageSlice.

    Args:
        slice_: Page slice to render.
        settings: Page settings.
        font_name: Font name for page numbers.
    Returns:
        PageTemplate for the content page.
    """

    return PageTemplate(
        id=slice_.template_id,
        frames=_content_frames(slice_=slice_, settings=settings),
        onPage=_on_page_factory(
            label=slice_.range_label,
            font_name=font_name,
            settings=settings,
        ),
    )


def _content_frames(*, slice_: PageSlice, settings: PageSettings) -> List[Frame]:
    """Single frame; footnotes follow the text naturally in flow order.

    Args:
        slice_: Page slice for the template.
        settings: Page settings.
    Returns:
        List of Frame objects.
    """

    return [
        Frame(
            settings.margin_left,
            settings.margin_bottom,
            settings.body_width,
            settings.body_height,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id=f"{slice_.template_id}-single",
            showBoundary=int(settings.debug_borders),
        )
    ]


def _page_flowables(*, slice_: PageSlice, settings: PageSettings) -> List:
    """Flowables needed to render a single page slice.

    Args:
        slice_: Page slice to render.
        settings: Page settings.
    Returns:
        List of flowables.
    """

    flows: List = []
    flows.extend(slice_.header_flowables)
    if slice_.header_flowables:
        flows.append(Spacer(1, settings.header_gap))
    blocks = slice_.text_blocks
    last_idx = len(blocks) - 1
    for idx, block in enumerate(blocks):
        if block.kind == "columns" and block.columns is not None:
            flows.append(
                _text_table(
                    columns=block.columns,
                    settings=settings,
                    extend_separator=bool(slice_.footnote_rows) and idx == last_idx,
                )
            )
            continue
        flows.extend(block.flowables)
    if slice_.footnote_rows:
        if not blocks or blocks[-1].kind != "columns":
            flows.append(Spacer(1, settings.column_gap / 2))
        flows.append(
            _footnote_table(
                rows=slice_.footnote_rows,
                row_heights=slice_.footnote_row_heights,
                row_lines=slice_.footnote_row_lines,
                settings=settings,
            )
        )
    return flows


def _story_for_pages(
    *,
    page_slices: Sequence[PageSlice],
    # toc_flow: Sequence[Paragraph],
    settings: PageSettings,
) -> List:
    """Assemble the platypus story.

    Args:
        page_slices: Pages to render.
        # toc_flow: Table of contents flowables.
        settings: Page settings.
    Returns:
        List of story flowables.
    """

    story: List = []
    # story.extend(toc_flow)
    if page_slices:
        story.append(NextPageTemplate(page_slices[0].template_id))
    # story.append(PageBreak())
    story.extend(_story_for_slices(page_slices=page_slices, settings=settings))
    if story:
        story.pop()
    return story


def _story_for_slices(
    *, page_slices: Sequence[PageSlice], settings: PageSettings
) -> List:
    """Return flowables for content page slices.

    Args:
        page_slices: Page slices to render.
        settings: Page settings.
    Returns:
        List of flowables.
    """

    story: List = []
    for idx, slice_ in enumerate(page_slices):
        story.extend(_page_flowables(slice_=slice_, settings=settings))
        if idx + 1 < len(page_slices):
            story.append(NextPageTemplate(page_slices[idx + 1].template_id))
        story.append(PageBreak())
    return story
