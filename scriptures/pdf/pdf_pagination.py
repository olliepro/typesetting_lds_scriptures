"""Public pagination helpers for PDF output."""

from __future__ import annotations

from .pdf_pagination_flow import _chapter_page_map, paginate_book, paginate_books

__all__ = [
    "_chapter_page_map",
    "paginate_book",
    "paginate_books",
]
