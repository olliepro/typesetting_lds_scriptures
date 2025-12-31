"""Extract hyphenated word splits from the published PDF."""

from __future__ import annotations

import argparse
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pdfplumber

PDF_URL = (
    "https://www.churchofjesuschrist.org/bc/content/shared/content/english/pdf/"
    "language-materials/83501_eng.pdf"
)
HYPHEN_CHARS = ("-", "\u00ad", "\u2010", "\u2011")
LINE_Y_TOLERANCE = 2.0
COLUMN_GAP_THRESHOLD = 8.0
WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class Word:
    """Word with layout metadata.

    Args:
        text: Word text.
        x0: Left edge position.
        x1: Right edge position.
        top: Top position.
    """

    text: str
    x0: float
    x1: float
    top: float


@dataclass(slots=True)
class LineGroup:
    """Cluster of words that share a line.

    Args:
        top: Top position for the line cluster.
        words: Words assigned to the line.
    """

    top: float
    words: list[Word]


@dataclass(slots=True)
class PageLine:
    """Extracted line metadata from a page.

    Args:
        text: Line text.
        x0: Left edge position.
        x1: Right edge position.
        top: Top position.
        column: Column label ("left", "right", or "full").
    """

    text: str
    x0: float
    x1: float
    top: float
    column: str


@dataclass(slots=True)
class HyphenSplit:
    """Hyphenated word split across PDF line wraps.

    Args:
        pdf_page: 1-based PDF page number.
        column: Column label ("left", "right", or "full").
        line_index: 1-based line index within the column.
        line_count: Total lines in the column.
        prefix: Word fragment before the hyphen.
        suffix: Word fragment after the hyphen.
        full_word: Reconstructed word without the hyphen.
        line_text: Text of the hyphenated line.
        next_line_text: Text of the following line.
    """

    pdf_page: int
    column: str
    line_index: int
    line_count: int
    prefix: str
    suffix: str
    full_word: str
    line_text: str
    next_line_text: str

    def tsv_row(self) -> str:
        """Return a TSV row for the split.

        Returns:
            Tab-separated string with line split details.

        Example:
            >>> split = HyphenSplit(
            ...     pdf_page=1,
            ...     column="left",
            ...     line_index=1,
            ...     line_count=2,
            ...     prefix="pro",
            ...     suffix="phet",
            ...     full_word="prophet",
            ...     line_text="pro-",
            ...     next_line_text="phet",
            ... )
            >>> "prophet" in split.tsv_row()
            True
        """

        values = [
            str(self.pdf_page),
            self.column,
            str(self.line_index),
            str(self.line_count),
            self.prefix,
            self.suffix,
            self.full_word,
            self.line_text,
            self.next_line_text,
        ]
        cleaned = [_tsv_safe(value=value) for value in values]
        return "\t".join(cleaned)


def _tsv_safe(*, value: str) -> str:
    """Return a TSV-safe string.

    Args:
        value: Raw string value.
    Returns:
        Value with tabs/newlines replaced by spaces.
    """

    return value.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _parse_args() -> argparse.Namespace:
    """Return CLI arguments for the extractor.

    Returns:
        argparse.Namespace of parsed CLI args.
    """

    parser = argparse.ArgumentParser(
        description="Extract hyphenated word splits from the official PDF."
    )
    parser.add_argument(
        "--pdf-url",
        type=str,
        default=PDF_URL,
        help="PDF URL to download when --pdf-path is not provided.",
    )
    parser.add_argument(
        "--pdf-path",
        type=Path,
        default=None,
        help="Path to a local PDF file.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("output/pdf_line_split_hyphens.tsv"),
        help="Output TSV path.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional cap on pages to scan.",
    )
    return parser.parse_args()


def _resolve_pdf_path(*, pdf_path: Path | None, pdf_url: str) -> Path:
    """Return a PDF path, downloading when needed.

    Args:
        pdf_path: Optional local PDF path.
        pdf_url: URL to download when pdf_path is not provided.
    Returns:
        Path to a local PDF file.
    """

    if pdf_path and pdf_path.exists():
        return pdf_path
    temp_dir = Path(tempfile.mkdtemp(prefix="scriptures_pdf_"))
    target = temp_dir / "scriptures.pdf"
    urllib.request.urlretrieve(pdf_url, target)
    return target


def _column_for_line(*, x0: float, x1: float, mid: float) -> str:
    """Return the column label for a line.

    Args:
        x0: Left edge position.
        x1: Right edge position.
        mid: Midpoint separating columns.
    Returns:
        Column label ("left", "right", or "full").
    """

    if x0 < mid and x1 > mid:
        return "full"
    if x0 < mid:
        return "left"
    return "right"


def _line_text(*, text: str) -> str:
    """Return normalized line text.

    Args:
        text: Raw line text.
    Returns:
        Line text with collapsed whitespace.
    """

    return _WHITESPACE_RE.sub(" ", text).strip()


def _extract_words(*, page: pdfplumber.page.Page) -> list[Word]:
    """Return extracted words for a page.

    Args:
        page: pdfplumber Page instance.
    Returns:
        List of Word entries with positions.
    """

    words: list[Word] = []
    for raw in page.extract_words():
        text = _line_text(text=str(raw.get("text", "")))
        if not text:
            continue
        words.append(
            Word(
                text=text,
                x0=float(raw.get("x0", 0.0)),
                x1=float(raw.get("x1", 0.0)),
                top=float(raw.get("top", 0.0)),
            )
        )
    return words


def _cluster_word_lines(*, words: list[Word]) -> list[LineGroup]:
    """Cluster words into line groups.

    Args:
        words: Words extracted from a page.
    Returns:
        List of LineGroup entries.
    """

    groups: list[LineGroup] = []
    for word in sorted(words, key=lambda item: item.top):
        placed = False
        for group in groups:
            if abs(word.top - group.top) <= LINE_Y_TOLERANCE:
                group.words.append(word)
                group.top = min(group.top, word.top)
                placed = True
                break
        if not placed:
            groups.append(LineGroup(top=word.top, words=[word]))
    return groups


def _words_to_line(*, words: list[Word], column: str) -> PageLine:
    """Return a PageLine from words.

    Args:
        words: Words on the line.
        column: Column label.
    Returns:
        PageLine entry.
    """

    sorted_words = sorted(words, key=lambda item: item.x0)
    text = _line_text(text=" ".join(word.text for word in sorted_words))
    x0 = min(word.x0 for word in sorted_words)
    x1 = max(word.x1 for word in sorted_words)
    top = min(word.top for word in sorted_words)
    return PageLine(text=text, x0=x0, x1=x1, top=top, column=column)


def _line_groups_to_lines(
    *, groups: list[LineGroup], mid: float
) -> list[PageLine]:
    """Return PageLine entries for clustered line groups.

    Args:
        groups: LineGroup entries.
        mid: Midpoint separating columns.
    Returns:
        List of PageLine entries.
    """

    lines: list[PageLine] = []
    for group in groups:
        words = sorted(group.words, key=lambda item: item.x0)
        left = [word for word in words if word.x0 < mid]
        right = [word for word in words if word.x0 >= mid]
        if left and right:
            gap = min(word.x0 for word in right) - max(word.x1 for word in left)
            if gap >= COLUMN_GAP_THRESHOLD:
                lines.append(_words_to_line(words=left, column="left"))
                lines.append(_words_to_line(words=right, column="right"))
                continue
        lines.append(
            _words_to_line(
                words=words,
                column=_column_for_line(x0=words[0].x0, x1=words[-1].x1, mid=mid),
            )
        )
    return lines


def _page_lines(*, page: pdfplumber.page.Page) -> list[PageLine]:
    """Return PageLine entries for a PDF page.

    Args:
        page: pdfplumber Page instance.
    Returns:
        List of PageLine entries.
    """

    mid = page.width / 2
    words = _extract_words(page=page)
    groups = _cluster_word_lines(words=words)
    return _line_groups_to_lines(groups=groups, mid=mid)


def _lines_by_column(*, lines: Iterable[PageLine]) -> dict[str, list[PageLine]]:
    """Group lines by column label.

    Args:
        lines: PageLine entries.
    Returns:
        Mapping from column label to sorted lines.
    """

    groups: dict[str, list[PageLine]] = {"left": [], "right": [], "full": []}
    for line in lines:
        groups.setdefault(line.column, []).append(line)
    for key in list(groups.keys()):
        groups[key] = sorted(groups[key], key=lambda item: item.top)
    return groups


def _ends_with_split_hyphen(*, text: str) -> bool:
    """Return True when text ends with a split hyphen.

    Args:
        text: Line text to inspect.
    Returns:
        True when the line ends with a hyphen character.
    """

    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in HYPHEN_CHARS


def _strip_trailing_hyphen(*, text: str) -> str:
    """Return text with a trailing hyphen removed.

    Args:
        text: Line text that may end with a hyphen.
    Returns:
        Text without the trailing hyphen.
    """

    stripped = text.rstrip()
    if stripped and stripped[-1] in HYPHEN_CHARS:
        return stripped[:-1]
    return stripped


def _first_word(*, text: str) -> str:
    """Return the first word token for a line.

    Args:
        text: Line text to inspect.
    Returns:
        First word token, or empty string if none found.
    """

    tokens = WORD_RE.findall(text)
    if not tokens:
        return ""
    if len(tokens) > 1 and len(tokens[0]) == 1:
        return tokens[1]
    return tokens[0]


def _last_word(*, text: str) -> str:
    """Return the last word token for a line.

    Args:
        text: Line text to inspect.
    Returns:
        Last word token, or empty string if none found.
    """

    tokens = WORD_RE.findall(text)
    if not tokens:
        return ""
    if len(tokens) > 1 and len(tokens[-1]) == 1:
        return tokens[-2]
    return tokens[-1]


def _prefix_for_split(*, line_text: str) -> str:
    """Return the prefix fragment for a hyphenated line.

    Args:
        line_text: Line text ending with a hyphen.
    Returns:
        Prefix fragment before the hyphen.
    """

    base = _strip_trailing_hyphen(text=line_text)
    tokens = WORD_RE.findall(base)
    if not tokens:
        return ""
    if len(tokens) >= 2 and len(tokens[-1]) == 1:
        prev = tokens[-2]
        last = tokens[-1]
        if len(prev) >= 2 and prev[0].islower() and prev[1].isupper():
            return prev[1:] + last
        if len(prev) == 1:
            return prev + last
    return _last_word(text=base)


def _suffix_for_split(*, next_text: str) -> str:
    """Return the suffix fragment from the next line.

    Args:
        next_text: Following line text.
    Returns:
        Suffix fragment after the split.
    """

    return _first_word(text=next_text)


def _iter_column_splits(
    *,
    lines: list[PageLine],
    pdf_page: int,
    column: str,
) -> Iterable[HyphenSplit]:
    """Yield HyphenSplit entries for a column.

    Args:
        lines: Column lines sorted by top position.
        pdf_page: 1-based PDF page number.
        column: Column label.
    Returns:
        Iterable of HyphenSplit entries.
    """

    total = len(lines)
    for idx in range(total - 1):
        line_text = lines[idx].text
        if not _ends_with_split_hyphen(text=line_text):
            continue
        next_text = lines[idx + 1].text
        prefix = _prefix_for_split(line_text=line_text)
        suffix = _suffix_for_split(next_text=next_text)
        if not prefix or not suffix:
            continue
        yield HyphenSplit(
            pdf_page=pdf_page,
            column=column,
            line_index=idx + 1,
            line_count=total,
            prefix=prefix,
            suffix=suffix,
            full_word=f"{prefix}{suffix}",
            line_text=line_text,
            next_line_text=next_text,
        )


def _iter_page_splits(*, page: pdfplumber.page.Page, pdf_page: int) -> Iterable[HyphenSplit]:
    """Yield HyphenSplit entries for a single PDF page.

    Args:
        page: pdfplumber Page instance.
        pdf_page: 1-based PDF page number.
    Returns:
        Iterable of HyphenSplit entries.
    """

    lines = _page_lines(page=page)
    grouped = _lines_by_column(lines=lines)
    for column, column_lines in grouped.items():
        yield from _iter_column_splits(
            lines=column_lines,
            pdf_page=pdf_page,
            column=column,
        )


def _iter_pdf_splits(
    *, pdf_path: Path, max_pages: int | None
) -> Iterable[HyphenSplit]:
    """Yield HyphenSplit entries for the PDF.

    Args:
        pdf_path: Local path to the PDF file.
        max_pages: Optional cap on pages to scan.
    Returns:
        Iterable of HyphenSplit entries.

    Example:
        >>> list(_iter_pdf_splits(pdf_path=Path(\"/tmp/sample.pdf\"), max_pages=0))
        []
    """

    with pdfplumber.open(pdf_path) as pdf:
        limit = len(pdf.pages) if max_pages is None else min(max_pages, len(pdf.pages))
        for index in range(limit):
            page = pdf.pages[index]
            yield from _iter_page_splits(page=page, pdf_page=index + 1)


def _write_splits(
    *, splits: Iterable[HyphenSplit], output_path: Path
) -> tuple[int, Path]:
    """Write hyphen splits to a TSV file.

    Args:
        splits: Iterable of HyphenSplit entries.
        output_path: Path to write the TSV file.
    Returns:
        Tuple of (count_written, resolved_path).
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "pdf_page",
        "column",
        "line_index",
        "line_count",
        "prefix",
        "suffix",
        "full_word",
        "line_text",
        "next_line_text",
    ]
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for split in splits:
            handle.write(split.tsv_row() + "\n")
            count += 1
    return count, output_path.resolve()


def main() -> None:
    """Run the PDF hyphen split extractor.

    Example:
        >>> main()  # doctest: +SKIP
    """

    args = _parse_args()
    pdf_path = _resolve_pdf_path(
        pdf_path=args.pdf_path,
        pdf_url=args.pdf_url,
    )
    count, output_path = _write_splits(
        splits=_iter_pdf_splits(pdf_path=pdf_path, max_pages=args.max_pages),
        output_path=args.output_path,
    )
    print(f"Wrote {count} hyphenated splits to {output_path}")


if __name__ == "__main__":
    main()
