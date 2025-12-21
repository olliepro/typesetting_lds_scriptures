"""Footnote helpers for chapter line building."""

from __future__ import annotations

from typing import Dict, List, Sequence

from ..models import FootnoteEntry
from .pdf_text_html import _footnote_letters


def _footnotes_by_verse(*, footnotes: Sequence[FootnoteEntry]) -> Dict[str, List[FootnoteEntry]]:
    """Group footnotes by verse number.

    Args:
        footnotes: Footnote entries for a chapter.
    Returns:
        Mapping from verse number to footnote list.
    """

    by_verse: Dict[str, List[FootnoteEntry]] = {}
    for entry in footnotes:
        by_verse.setdefault(entry.verse, []).append(entry)
    return by_verse


def _footnote_map(
    *, verse_number: str | None, footnotes_by_verse: Dict[str, List[FootnoteEntry]]
) -> Dict[str, FootnoteEntry]:
    """Return a letter->footnote mapping for a verse.

    Args:
        verse_number: Verse number key.
        footnotes_by_verse: Footnotes grouped by verse.
    Returns:
        Mapping of footnote letters to entries.
    """

    if verse_number is None:
        return {}
    return {
        entry.letter.lower(): entry
        for entry in footnotes_by_verse.get(verse_number, [])
    }


def _collect_line_footnotes(
    *,
    line_html: str,
    footnote_map: Dict[str, FootnoteEntry],
    assigned_letters: set[str],
) -> List[FootnoteEntry]:
    """Collect unassigned footnotes for the line.

    Args:
        line_html: Line HTML fragment.
        footnote_map: Mapping of letters to footnotes.
        assigned_letters: Set of letters already assigned.
    Returns:
        List of footnote entries for this line.
    """

    letters = _footnote_letters(html=line_html)
    notes = [
        footnote_map[lt]
        for lt in letters
        if lt in footnote_map and lt not in assigned_letters
    ]
    assigned_letters.update(lt for lt in letters if lt in footnote_map)
    return notes
