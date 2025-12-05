"""Debug PDF comparing footnote layout variants.

Page shows two two-column tables built from a Genesis 1 footnote sample:
1) Normal footnotes (one row per entry).
2) Line-split footnotes (one row per wrapped line; verse/letter only on first line).
"""

from pathlib import Path
import sys

from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyphen import Pyphen

from scriptures.pdf_builder import (
    PageSettings,
    _footnote_column_widths,
    _footnote_rows,
    _footnote_table,
    _line_fragments,
    build_styles,
    measure_height,
    register_palatino,
)
from scriptures.models import FootnoteEntry


def _sample_entries() -> list[FootnoteEntry]:
    """Return a few Genesis 1-style footnotes for column testing."""

    return [
        FootnoteEntry(chapter="1", verse="1", letter="a", text="HEB the earth was empty and desolate.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="2", letter="a", text="TG Earth; Water", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="3", letter="a", text="HEB Let there be light: and there was light; or, there shall be light; and there was light.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="4", letter="a", text="HEB divided the light from the darkness: Heb separated between the light and between the darkness.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="5", letter="a", text="HEB And it was evening, and it was morning, one day.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="6", letter="a", text="HEB expanse; i.e., the firmament or expanse of heaven.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="7", letter="a", text="HEB made the expanse and separated the waters.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="8", letter="a", text="HEB Heaven; i.e., sky or expanse.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="9", letter="a", text="HEB gathered into one place; dry land appeared.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="10", letter="a", text="HEB Earth and Seas; naming signifies ordering.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="11", letter="a", text="HEB herbs yielding seed and fruit trees yielding fruit.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="12", letter="a", text="HEB after its kind; recurring formula of order.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="13", letter="a", text="HEB third day completed.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="14", letter="a", text="HEB Let there be lights in the expanse of heaven to divide day from night.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="15", letter="a", text="HEB give light upon the earth; serve as signs and seasons.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="16", letter="a", text="HEB two great lights; greater for the day, lesser for the night; also the stars.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="17", letter="a", text="HEB set them in the expanse of heaven; appointed their stations.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="18", letter="a", text="HEB to rule over the day and over the night, and to divide the light from the darkness.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="19", letter="a", text="HEB fourth day finished.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="20", letter="a", text="HEB swarm with swarms of living creatures; birds fly above the earth.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="21", letter="a", text="HEB created the great sea creatures and every living creature that moves.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="22", letter="a", text="HEB be fruitful and multiply; fill the waters; birds multiply in the earth.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="23", letter="a", text="HEB fifth day completed.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="24", letter="a", text="HEB earth bring forth living creatures after their kind.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="25", letter="a", text="HEB beasts of the earth after their kind; order and taxonomy implied.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="26", letter="a", text="HEB Let us make man in our image; dominion language.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="27", letter="a", text="HEB created male and female; image-bearing highlighted.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="28", letter="a", text="HEB be fruitful, multiply, replenish the earth, subdue it, have dominion.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="29", letter="a", text="HEB every herb bearing seed and tree with fruit for meat.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="30", letter="a", text="HEB green herb given to every beast, fowl, and creeping thing for meat.", segments=[], links=[]),
        FootnoteEntry(chapter="1", verse="31", letter="a", text="HEB behold, it was very good; sixth day concluded.", segments=[], links=[]),
    ]


def _split_rows_by_lines(rows, styles, text_width):
    """Return new rows where each wrapped line becomes its own row."""

    split_rows = []
    split_heights = []
    split_lines = []
    line_no = 1
    for ch, vs, lt, para in rows:
        line_htmls = _line_fragments(para, text_width)
        for idx, html in enumerate(line_htmls):
            ch_cell = ch if (idx == 0) else ""
            vs_cell = vs if (idx == 0) else ""
            lt_cell = lt if (idx == 0) else ""
            line_para = Paragraph(html, styles["footnote"])
            h = measure_height(line_para, text_width) + 2 * PageSettings().footnote_row_padding
            split_rows.append((ch_cell, vs_cell, lt_cell, str(line_no), line_para))
            split_heights.append(h)
            split_lines.append(1)
            line_no += 1
    return split_rows, split_heights, split_lines


def build_tables(show_line_numbers: bool):
    settings = PageSettings()
    font = register_palatino()
    styles = build_styles(font)
    hyphenator = Pyphen(lang="en_US")

    entries = _sample_entries()
    rows, heights, lines, _ = _footnote_rows(entries, styles, hyphenator, settings)

    include_ch = any(ch for ch, _, _, _ in rows)
    ch_w, vs_w, lt_w, txt_w = _footnote_column_widths(rows, include_ch, settings)

    # Normal table
    slice_normal = type("Slice", (), {})()
    slice_normal.footnote_rows = rows
    slice_normal.footnote_row_heights = heights
    slice_normal.footnote_row_lines = lines
    table_a = _footnote_table(slice_normal, settings)

    split_rows, split_heights, split_lines = _split_rows_by_lines(rows, styles, txt_w)
    # Fill columns left-to-right in reading order by simple chunking
    cols = 2
    per_col = (len(split_rows) + cols - 1) // cols
    ordered_rows = []
    ordered_heights = []
    ordered_lines = []
    for c in range(cols):
        start = c * per_col
        end = min(len(split_rows), start + per_col)
        ordered_rows.extend(split_rows[start:end])
        ordered_heights.extend(split_heights[start:end])
        ordered_lines.extend(split_lines[start:end])
    slice_like2 = type("Slice", (), {})()
    # Build split view table, optional line-number column, filling columns left->right
    include_ch = any(ch for ch, _, _, _, _ in ordered_rows)
    ch_w, vs_w, lt_w, txt_w = _footnote_column_widths(
        [(ch, vs, lt, para) for ch, vs, lt, _, para in ordered_rows], include_ch, settings
    )
    line_w = 14 if show_line_numbers else 0
    cols = 3
    per_col = (len(ordered_rows) + cols - 1) // cols
    column_tables = []
    for c in range(cols):
        start = c * per_col
        end = min(len(ordered_rows), start + per_col)
        segment = ordered_rows[start:end]
        seg_heights = ordered_heights[start:end]
        if not segment:
            column_tables.append(Spacer(1, 0))
            continue
        data = []
        widths = []
        for (ch, vs, lt, ln, para), h in zip(segment, seg_heights):
            row = []
            if show_line_numbers:
                row.append(ln)
            row.extend([ch, vs, lt, para] if include_ch else [vs, lt, para])
            data.append(row)
        if show_line_numbers:
            widths.append(line_w)
        if include_ch:
            widths.extend([ch_w, vs_w, lt_w, txt_w])
        else:
            widths.extend([vs_w, lt_w, txt_w])
        tbl = Table(data, colWidths=widths, rowHeights=seg_heights, hAlign="LEFT")
        tbl.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), settings.footnote_row_padding),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), settings.footnote_row_padding),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("FONTNAME", (0, 0), (-1, -1), settings.font_name),
                ]
                + ([("ALIGN", (0, 0), (0, -1), "RIGHT")] if show_line_numbers else [])
            )
        )
        column_tables.append(tbl)
    table_b = Table(
        [[column_tables[0], "", column_tables[1], "", column_tables[2]]],
        colWidths=[
            settings.footnote_column_width(),
            settings.column_gap,
            settings.footnote_column_width(),
            settings.column_gap,
            settings.footnote_column_width(),
        ],
        hAlign="LEFT",
    )
    table_b.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LINEBEFORE", (2, 0), (2, 0), 0.4, colors.lightgrey),
                ("LINEBEFORE", (4, 0), (4, 0), 0.4, colors.lightgrey),
            ]
        )
    )

    return table_a, table_b


def main() -> None:
    settings = PageSettings()
    output = Path("output")
    output.mkdir(parents=True, exist_ok=True)

    for label, show_lines in (("with-lines", True), ("no-lines", False)):
        table_a, table_b = build_tables(show_lines)

        doc = SimpleDocTemplate(
            str(output / f"debug-footnote-compare-{label}.pdf"),
            pagesize=letter,
            leftMargin=settings.margin_left,
            rightMargin=settings.margin_right,
            topMargin=settings.margin_top,
            bottomMargin=settings.margin_bottom,
        )

        story = [
            Paragraph("Footnote Table A (normal rows)", build_styles(register_palatino())["preface"]),
            Spacer(1, 6),
            table_a,
            Spacer(1, 18),
            Paragraph(f"Footnote Table B (line-split rows{' + line numbers' if show_lines else ''})", build_styles(register_palatino())["preface"]),
            Spacer(1, 6),
            table_b,
        ]
        doc.build(story)


if __name__ == "__main__":
    main()
