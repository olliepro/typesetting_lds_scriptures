"""Verse range labels for page headers."""

from __future__ import annotations

import re
from typing import Dict, Sequence

from ..models import Book
from .pdf_types import FlowItem


def _range_label(*, items: Sequence[FlowItem], book_lookup: Dict[str, Book]) -> str:
    """Return the display label for a page range.

    Args:
        items: FlowItems on the page.
        book_lookup: Lookup of book slug to Book.
    Returns:
        Range label string.
    """

    verses = [item for item in items if item.is_verse]
    if not verses:
        return _non_verse_range_label(items=items, book_lookup=book_lookup)
    first = _starting_verse_item(verses=verses) or verses[0]
    last = verses[-1]
    book = book_lookup.get(first.book_slug)
    start_title = _chapter_title_from_item(item=first, book=book)
    end_book = book_lookup.get(last.book_slug)
    end_title = _chapter_title_from_item(item=last, book=end_book)
    if first.chapter == last.chapter:
        return _chapter_verse_label(
            chapter_title=start_title,
            start_verse=first.verse or "",
            end_verse=last.verse or "",
        )
    if first.book_slug == last.book_slug:
        book_name = _book_name_from_titles(
            start_title=start_title,
            end_title=end_title,
            fallback=_book_name_from_book(book),
        )
        return _same_book_range_label(
            book_name=book_name,
            start_chapter=first.chapter,
            start_verse=first.verse or "",
            end_chapter=last.chapter,
            end_verse=last.verse or "",
        )
    return _cross_book_range_label(
        start_title=start_title,
        start_verse=first.verse or "",
        end_title=end_title,
        end_verse=last.verse or "",
    )


def _chapter_title(*, book: Book | None, chapter_number: str, fallback: str) -> str:
    """Return the chapter title for a chapter number.

    Args:
        book: Book containing the chapter.
        chapter_number: Chapter identifier to match.
        fallback: Fallback title when no match exists.
    Returns:
        Chapter title string.
    """

    if book is None:
        return fallback
    for chapter in book.chapters:
        if chapter.number == chapter_number:
            return chapter.title or fallback
    return fallback


def _chapter_title_from_item(*, item: FlowItem, book: Book | None) -> str:
    """Return the chapter title associated with a FlowItem.

    Args:
        item: FlowItem carrying chapter metadata.
        book: Optional book to resolve chapter titles.
    Returns:
        Chapter title string.
    """

    fallback = item.chapter_title or item.book_name
    if book is None:
        return fallback
    return _chapter_title(
        book=book,
        chapter_number=item.chapter,
        fallback=fallback,
    )


def _starting_verse_item(*, verses: Sequence[FlowItem]) -> FlowItem | None:
    """Return the first verse line that starts a verse on the page.

    Args:
        verses: Verse FlowItems in page order.
    Returns:
        First FlowItem that begins a verse, or None.
    """

    return next((item for item in verses if item.first_line), None)


def _book_name_from_book(book: Book | None) -> str:
    """Return the preferred book name for labeling.

    Args:
        book: Optional Book object.
    Returns:
        Book name or empty string.
    """

    if book is None:
        return ""
    return book.abbrev or book.name


def _book_name_from_titles(*, start_title: str, end_title: str, fallback: str) -> str:
    """Return a book name derived from chapter titles.

    Args:
        start_title: Chapter title for the start of the range.
        end_title: Chapter title for the end of the range.
        fallback: Fallback book name.
    Returns:
        Book name string.
    """

    for title in (start_title, end_title):
        candidate = _book_name_from_chapter_title(chapter_title=title)
        if candidate:
            return candidate
    return fallback


def _book_name_from_chapter_title(*, chapter_title: str) -> str:
    """Strip the trailing chapter number from a chapter title.

    Args:
        chapter_title: Chapter title containing a trailing chapter number.
    Returns:
        Book name without the chapter number.
    """

    return re.sub(r"\s+\d+[A-Za-z]?$", "", chapter_title).strip()


def _same_book_range_label(
    *,
    book_name: str,
    start_chapter: str,
    start_verse: str,
    end_chapter: str,
    end_verse: str,
) -> str:
    """Return a range label for chapters within the same book.

    Args:
        book_name: Book name to display.
        start_chapter: Starting chapter identifier.
        start_verse: Starting verse identifier.
        end_chapter: Ending chapter identifier.
        end_verse: Ending verse identifier.
    Returns:
        Formatted label string.
    """

    if start_chapter == end_chapter:
        return _chapter_verse_label(
            chapter_title=f"{book_name} {start_chapter}",
            start_verse=start_verse,
            end_verse=end_verse,
        )
    return (
        f"{book_name} {start_chapter}:{start_verse}\u2013" f"{end_chapter}:{end_verse}"
    )


def _cross_book_range_label(
    *, start_title: str, start_verse: str, end_title: str, end_verse: str
) -> str:
    """Return a range label spanning two books.

    Args:
        start_title: Chapter title at the start of the range.
        start_verse: Starting verse identifier.
        end_title: Chapter title at the end of the range.
        end_verse: Ending verse identifier.
    Returns:
        Formatted label string.
    """

    return f"{start_title}:{start_verse}\u2013{end_title}:{end_verse}"


def _chapter_verse_label(
    *, chapter_title: str, start_verse: str, end_verse: str
) -> str:
    """Return a label using a chapter title plus verse range.

    Args:
        chapter_title: Chapter name/title to display.
        start_verse: First verse identifier.
        end_verse: Last verse identifier.
    Returns:
        Formatted label string.
    """

    if start_verse == end_verse:
        return f"{chapter_title}:{start_verse}"
    return f"{chapter_title}:{start_verse}\u2013{end_verse}"


def _non_verse_range_label(
    *, items: Sequence[FlowItem], book_lookup: Dict[str, Book]
) -> str:
    """Return a range label for pages without verses.

    Args:
        items: FlowItems on the page.
        book_lookup: Lookup of book slug to Book.
    Returns:
        Range label string for non-verse pages.
    """

    chapter_items = [item for item in items if item.chapter]
    if not chapter_items:
        return ""
    start_item = chapter_items[0]
    end_item = chapter_items[-1]
    start_chapter = start_item.chapter
    end_chapter = end_item.chapter
    book_slug = start_item.book_slug
    if book_slug == "official-declarations":
        return _official_declaration_label(
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
    book = book_lookup.get(book_slug)
    start_title = _chapter_title_from_item(item=start_item, book=book)
    if start_chapter == end_chapter:
        return start_title
    end_title = _chapter_title_from_item(item=end_item, book=book)
    return f"{start_title}\u2013{end_title}"


def _official_declaration_label(*, start_chapter: str, end_chapter: str) -> str:
    """Return a label for official declaration pages.

    Args:
        start_chapter: Starting declaration number.
        end_chapter: Ending declaration number.
    Returns:
        Uppercase official declaration label.
    """

    base = "OFFICIAL DECLARATION"
    if start_chapter == end_chapter:
        return f"{base} {start_chapter}"
    return f"{base} {start_chapter}-{end_chapter}"
