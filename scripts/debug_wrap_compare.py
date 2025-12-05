"""
Generate a small debug PDF showing two rendering strategies side by side.

Left column: one justified paragraph containing two verses (scriptures styles).
Right column: the same wrapped lines rendered as individual paragraphs.
"""

from pathlib import Path
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyphen import Pyphen

from scriptures.models import Verse
from scriptures.pdf_builder import (
    PageSettings,
    _line_fragments,
    _paragraph_from_html,
    build_styles,
    register_palatino,
)


def _sample_html() -> str:
    """Return a two-verse HTML snippet with longer text and a forced break."""

    indent = "&nbsp;&nbsp;"
    verses = [
        Verse(
            chapter="1",
            number="3",
            html="And God said, Let there be light: and there was light. And the light continued to shine upon the waters, carrying warmth and showing form.",
            plain_text="",
            compare_id="",
        ),
        Verse(
            chapter="1",
            number="4",
            html="And God saw the light, that it was good: and God divided the light from the darkness, setting a firm boundary so that the evening and the morning were the first day.",
            plain_text="",
            compare_id="",
        ),
    ]

    def _markup(v: Verse) -> str:
        return f"{indent}<b>{v.number}</b>&nbsp;{v.html}"

    # Force verse 4 to begin on a new line (no extra blank line).
    return "<br/>".join(_markup(v) for v in verses)


def _build_table(styles, settings, hyphenator: Pyphen):
    """Create the two-column comparison table using scripture column styling."""

    col_width = settings.text_column_width()
    center_pad = settings.column_gap * 1.5  # widen center spacing for clarity
    avail_width = col_width - center_pad / 2  # effective width after inner padding
    base_para = _paragraph_from_html(_sample_html(), styles["body"], hyphenator)
    line_htmls = _line_fragments(base_para, avail_width)

    per_line_paras = []
    for idx, html in enumerate(line_htmls):
        style = styles["body"] if idx == 0 else styles["body-cont"]
        per_line_paras.append(Paragraph(html, style))

    table = Table(
        [
            [
                Paragraph("Single paragraph (justified)", styles["preface"]),
                Paragraph("Per-line paragraphs", styles["preface"]),
            ],
            [base_para, per_line_paras],
        ],
        colWidths=[col_width, col_width],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 1), center_pad / 2),
                ("LEFTPADDING", (1, 0), (1, 1), center_pad / 2),
                ("LINEBEFORE", (1, 0), (1, 1), 0.4, colors.lightgrey),
            ]
        )
    )
    return table


def main() -> None:
    """Build ``output/debug-wrap-compare.pdf``."""

    settings = PageSettings()
    font = register_palatino()
    styles = build_styles(font)
    hyphenator = Pyphen(lang="en_US")
    output = Path("output/debug-wrap-compare.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=settings.margin_left,
        rightMargin=settings.margin_right,
        topMargin=settings.margin_top,
        bottomMargin=settings.margin_bottom,
    )

    story = [Spacer(1, 6), _build_table(styles, settings, hyphenator)]
    doc.build(story)


if __name__ == "__main__":
    main()
