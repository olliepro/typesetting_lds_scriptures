"""
Typed containers for scraped scripture content.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List


@dataclass(slots=True)
class FootnoteLink:
    """A hyperlink found inside a footnote entry.

    Attributes:
        text: The display text of the hyperlink.
        href: Absolute or document-relative link target.
        is_internal: True when the target belongs to the same standard work.
    """

    text: str
    href: str
    is_internal: bool


@dataclass(slots=True)
class FootnoteEntry:
    """Flattened footnote entry keyed by book, chapter, verse, and letter."""

    book_slug: str
    chapter: str
    verse: str
    letter: str
    text: str
    segments: List[str]
    links: List[FootnoteLink] = field(default_factory=list)

    def label(self) -> str:
        """Return a compact label such as '3a'."""
        return f"{self.verse}{self.letter}"


@dataclass(slots=True)
class Verse:
    """Represents a verse with its inline footnote markers."""

    chapter: str
    number: str
    html: str
    plain_text: str
    compare_id: str


@dataclass(slots=True)
class Chapter:
    """Chapter-level content parsed from the scraper output."""

    standard_work: str
    book: str
    number: str
    abbrev: str | None
    title: str
    header_blocks: List[tuple[str, str]]
    paragraphs: List[dict]
    verses: List[Verse]
    footnotes: List[FootnoteEntry]
    source_path: Path

    def verse_range(self) -> str:
        """Return a human-friendly range, e.g. '1–18'.

        Example:
            >>> Chapter(standard_work='old-testament', book='genesis', number='1', title='Genesis 1', header_blocks=[], paragraphs=[], verses=[Verse('1','1','','',''), Verse('1','2','','','')], footnotes=[], source_path=Path('tmp')).verse_range()
            '1–2'
        """

        if not self.verses:
            return ""
        start, end = self.verses[0].number, self.verses[-1].number
        return start if start == end else f"{start}\u2013{end}"


@dataclass(slots=True)
class Book:
    """Collection of chapters for a given book."""

    standard_work: str
    name: str
    slug: str
    abbrev: str | None
    chapters: List[Chapter]


@dataclass(slots=True)
class StandardWork:
    """Top-level grouping of books (e.g., Old Testament)."""

    name: str
    slug: str
    books: List[Book]


def flatten_chapters(books: Iterable[Book]) -> List[Chapter]:
    """Expand all chapters from the provided books into a single list.

    Example:
        >>> len(flatten_chapters([Book('bom','1 Nephi','1-nephi',[])]))
        0
    """

    result: List[Chapter] = []
    for book in books:
        result.extend(book.chapters)
    return result
