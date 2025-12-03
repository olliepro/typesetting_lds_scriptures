from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from bs4 import BeautifulSoup
from pyphen import Pyphen
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table

from .clean import clean_html, normalize_whitespace

# Mapping from scripture paths to standard work keys
STANDARD_WORKS = {
    "ot": "old-testament",
    "nt": "new-testament",
    "bofm": "book-of-mormon",
    "dc-testament": "doctrine-and-covenants",
    "pgp": "pearl-of-great-price",
}

FONT_NAME = "TeXGyrePagella"
FONT_FILES = [
    ("/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyrepagella-regular.otf", FONT_NAME),
    ("/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyrepagella-bold.otf", f"{FONT_NAME}-Bold"),
    ("/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyrepagella-italic.otf", f"{FONT_NAME}-Italic"),
]


def register_fonts() -> None:
    for path, name in FONT_FILES:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                continue


def default_styles(hyphenator: Pyphen) -> Dict[str, ParagraphStyle]:
    register_fonts()
    base_font = FONT_NAME if FONT_NAME in pdfmetrics.getRegisteredFontNames() else "Times-Roman"
    base = ParagraphStyle(
        "base",
        fontName=base_font,
        fontSize=10.5,
        leading=12,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
        hyphenationLang=getattr(hyphenator, "lang", None),
    )
    verse = ParagraphStyle("verse", parent=base, firstLineIndent=12)
    header = ParagraphStyle("header", parent=base, fontSize=9, leading=10)
    footnote = ParagraphStyle(
        "footnote",
        parent=base,
        fontSize=8,
        leading=9,
        alignment=TA_JUSTIFY,
        spaceAfter=2,
    )
    return {"base": base, "verse": verse, "header": header, "footnote": footnote}


@dataclass
class FootnoteEntry:
    chapter: str
    verse: str
    letter: str
    text: str
    href: str | None = None
    work: str | None = None


@dataclass
class Verse:
    work: str
    book: str
    chapter: str
    number: str
    text_html: str
    footnote_markers: List[str]

    @property
    def marker_label(self) -> str:
        return f"{self.chapter}:{self.number}"


@dataclass
class Chapter:
    work: str
    book: str
    chapter: str
    paragraphs: List[Verse]
    footnotes: List[FootnoteEntry]


@dataclass
class Page:
    verses: List[Verse] = field(default_factory=list)
    footnotes: List[FootnoteEntry] = field(default_factory=list)
    headers: Tuple[str, str] | None = None
    start_marker: str | None = None
    end_marker: str | None = None


class FootnoteParser:
    def __init__(self, work: str, book: str, chapter: str) -> None:
        self.work = work
        self.book = book
        self.chapter = chapter

    def parse(self, html: str) -> List[FootnoteEntry]:
        soup = BeautifulSoup(html, "lxml")
        entries: List[FootnoteEntry] = []
        for outer in soup.select("li[data-marker]"):
            verse = outer.get("data-marker", "")
            for item in outer.select("li[data-full-marker]"):
                letter = item.get("data-marker", "")
                text = normalize_whitespace(item.get_text(" "))
                href = None
                href_target_work = None
                ref = item.select_one("a[href]")
                if ref and ref.has_attr("href"):
                    href = ref["href"]
                    href_target_work = self._resolve_work_from_href(href)
                entries.append(
                    FootnoteEntry(
                        chapter=self.chapter,
                        verse=verse,
                        letter=letter,
                        text=text,
                        href=href,
                        work=href_target_work,
                    )
                )
        return entries

    def _resolve_work_from_href(self, href: str | None) -> str | None:
        if not href:
            return None
        if href.startswith("http"):
            for key, work in STANDARD_WORKS.items():
                if f"/{key}/" in href:
                    return work
            return None
        if href.startswith("/"):
            for key, work in STANDARD_WORKS.items():
                if href.split("/")[2] == key:
                    return work
        return None


def extract_verses(chapter_dict: dict, work: str, book: str) -> Chapter:
    paragraphs = []
    footnote_html = None
    chapter_number = chapter_dict.get("number", "")
    for para in chapter_dict.get("paragraphs", []):
        if para.get("type") == "study-footnotes":
            footnote_html = para.get("contentHtml", "")
            continue
        if para.get("type") not in {"verse", "study-paragraph"}:
            continue
        html = para.get("contentHtml") or para.get("content") or ""
        markers = [link.get("data-value", "") for link in BeautifulSoup(html, "lxml").select("sup")]
        paragraphs.append(
            Verse(
                work=work,
                book=book,
                chapter=chapter_number,
                number=para.get("number", ""),
                text_html=html,
                footnote_markers=markers,
            )
        )
    notes: List[FootnoteEntry] = []
    if footnote_html:
        notes = FootnoteParser(work, book, chapter_number).parse(footnote_html)
    return Chapter(work=work, book=book, chapter=chapter_number, paragraphs=paragraphs, footnotes=notes)


def format_paragraph(html: str, style: ParagraphStyle) -> Paragraph:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(True):
        if tag.name == "a":
            tag.attrs = {k: v for k, v in tag.attrs.items() if k == "href"}
        elif tag.name == "sup":
            tag.attrs = {}
        else:
            tag.attrs = {}
    for sup in soup.find_all("sup"):
        sup.string = sup.get("data-value") or sup.text or ""
    cleaned = str(soup)
    return Paragraph(cleaned, style)


def split_rows(rows: List[List[str]], columns: int = 3) -> List[List[List[str]]]:
    per_col = math.ceil(len(rows) / columns) if rows else 0
    return [rows[i * per_col : (i + 1) * per_col] for i in range(columns)]


def build_footnote_rows(footnotes: Sequence[FootnoteEntry]) -> List[List[str]]:
    rows: List[List[str]] = []
    prev_chapter = prev_verse = None
    for entry in sorted(footnotes, key=lambda f: (int(f.chapter), int(f.verse or 0), f.letter)):
        chap = entry.chapter if entry.chapter != prev_chapter else ""
        verse = entry.verse if entry.verse != prev_verse else ""
        rows.append([chap, verse, entry.letter, entry.text])
        prev_chapter, prev_verse = entry.chapter, entry.verse
    return rows


def estimate_table_height(table: Table, width: float) -> float:
    _, height = table.wrapOn(canvas.Canvas(None), width, 1000)
    return height


def draw_vertical_guides(c: canvas.Canvas, x_positions: List[float], y0: float, y1: float) -> None:
    for x in x_positions:
        c.line(x, y0, x, y1)


def render_pdf(output: Path, pages: List[Page], styles: Dict[str, ParagraphStyle]) -> None:
    c = canvas.Canvas(str(output), pagesize=LETTER)
    width, height = LETTER
    toc_entries: List[Tuple[str, int]] = []

    content_start_page = 2  # reserve one page for the TOC
    for index, page in enumerate(pages):
        page_number = index + content_start_page
        if page.headers:
            toc_entries.append((page.headers[0], page_number))

    # Table of contents page
    c.setFont(styles["header"].fontName, 14)
    c.drawString(1 * inch, height - 1.25 * inch, "Table of Contents")
    c.setFont(styles["header"].fontName, 10)
    y = height - 1.75 * inch
    for title, page_num in toc_entries:
        c.drawString(1 * inch, y, title)
        c.drawRightString(width - 1 * inch, y, str(page_num))
        y -= 14
    c.showPage()

    header_height = 0.4 * inch
    margin = 0.65 * inch
    column_gap = 0.25 * inch

    for index, page in enumerate(pages):
        page_number = index + content_start_page
        # Header
        c.setFont(styles["header"].fontName, 9)
        c.drawString(margin, height - margin + 4, str(page_number))
        if page.start_marker and page.end_marker:
            c.drawRightString(width - margin, height - margin + 4, f"{page.start_marker}–{page.end_marker}")

        y_cursor = height - margin - header_height
        available_height = y_cursor - margin
        footnote_rows = build_footnote_rows(page.footnotes)
        col_width = (width - 2 * margin - 2 * column_gap) / 3
        footnote_tables = []
        columned_rows = split_rows(footnote_rows, 3)
        max_footnote_height = 0
        for bucket in columned_rows:
            if not bucket:
                footnote_tables.append(None)
                continue
            tbl = Table(bucket, colWidths=[18, 18, 12, col_width - 48])
            tbl.setStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), styles["footnote"].fontSize),
                    ("LEADING", (0, 0), (-1, -1), styles["footnote"].leading),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("ALIGN", (2, 0), (2, -1), "LEFT"),
                ]
            )
            footnote_tables.append(tbl)
            max_footnote_height = max(max_footnote_height, estimate_table_height(tbl, col_width))

        text_area_height = available_height - max_footnote_height - 8
        text_width = (width - 2 * margin - column_gap) / 2
        x_positions = [margin, margin + text_width + column_gap]
        column_bottom = margin + max_footnote_height + 4

        current_col = 0
        col_heights = [0.0, 0.0]
        start_marker = None
        end_marker = None
        for verse in page.verses:
            para = format_paragraph(verse.text_html, styles["verse"])
            w, h = para.wrap(text_width, text_area_height)
            if col_heights[current_col] + h > text_area_height:
                if current_col == 0:
                    current_col = 1
                    w, h = para.wrap(text_width, text_area_height)
                    col_heights[current_col] = 0
                else:
                    c.showPage()
                    page_number += 1
                    current_col = 0
                    col_heights = [0.0, 0.0]
                    c.setFont(styles["header"].fontName, 9)
                    c.drawString(margin, height - margin + 4, str(page_number))
            x = x_positions[current_col]
            y = height - margin - header_height - col_heights[current_col] - h
            para.drawOn(c, x, y)
            col_heights[current_col] += h
            start_marker = start_marker or verse.marker_label
            end_marker = verse.marker_label

        if max_footnote_height:
            footnote_y = margin
            c.setLineWidth(0.5)
            c.line(margin, footnote_y + max_footnote_height + 2, width - margin, footnote_y + max_footnote_height + 2)
            for idx, tbl in enumerate(footnote_tables):
                x = margin + idx * (col_width + column_gap)
                if not tbl:
                    continue
                _, h = tbl.wrap(col_width, max_footnote_height)
                tbl.drawOn(c, x, footnote_y)
                if idx < 2:
                    c.line(x + col_width, footnote_y, x + col_width, footnote_y + max_footnote_height)

        c.showPage()

    c.save()


def paginate(chapters: Iterable[Chapter], styles: Dict[str, ParagraphStyle]) -> List[Page]:
    pages: List[Page] = []
    current_page = Page()
    max_verses_per_page = 50
    for chapter in chapters:
        for verse in chapter.paragraphs:
            markers = {f"{chapter.chapter}:{verse.number}{m}" for m in verse.footnote_markers}
            relevant_notes = [note for note in chapter.footnotes if f"{note.verse}{note.letter}" in {f"{verse.number}{m}" for m in verse.footnote_markers}]
            candidate_footnotes = current_page.footnotes + relevant_notes
            # naive pagination: break page if footnotes would overrun the page height limit
            if len(candidate_footnotes) > 20 or len(current_page.verses) >= max_verses_per_page:
                pages.append(current_page)
                current_page = Page()
            current_page.verses.append(verse)
            for note in relevant_notes:
                if note not in current_page.footnotes:
                    current_page.footnotes.append(note)
            if not current_page.headers:
                current_page.headers = (chapter.book.title(), chapter.book.title())
        if current_page.verses:
            current_page.end_marker = current_page.verses[-1].marker_label
            current_page.start_marker = current_page.verses[0].marker_label
    if current_page.verses:
        pages.append(current_page)
    return pages
