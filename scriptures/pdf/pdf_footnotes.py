"""Facade for footnote layout and table helpers."""

from __future__ import annotations

from .pdf_footnotes_layout import (
    FootnoteRowText,
    _code_map_from_metadata,
    _footnote_column_widths,
    _footnote_height,
    _footnote_rows,
    _footnotes_for_items,
    _place_footnotes,
    _range_label,
    _refresh_footnotes,
)
from .pdf_footnotes_tables import FootnoteBlock, _footnote_table

__all__ = [
    "FootnoteBlock",
    "FootnoteRowText",
    "_code_map_from_metadata",
    "_footnote_column_widths",
    "_footnote_height",
    "_footnote_rows",
    "_footnote_table",
    "_footnotes_for_items",
    "_place_footnotes",
    "_range_label",
    "_refresh_footnotes",
]
