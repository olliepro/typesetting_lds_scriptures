"""Validate spacing around small caps and superscript prefixes in section 135 PDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, List

from pypdf import PdfReader


@dataclass(frozen=True, slots=True)
class TextCheck:
    """Expectation for normalized PDF text.

    Args:
        label: Human-readable label for the check.
        must_contain: Required substring after normalization.
        must_not_contain: Forbidden substring after normalization.
    """

    label: str
    must_contain: str | None = None
    must_not_contain: str | None = None

    def evaluate(self, *, text: str) -> List[str]:
        """Return a list of failure messages for this check."""

        failures: List[str] = []
        if self.must_contain and self.must_contain not in text:
            failures.append(f"{self.label}: missing '{self.must_contain}'")
        if self.must_not_contain and self.must_not_contain in text:
            failures.append(f"{self.label}: found '{self.must_not_contain}'")
        return failures


def _extract_layout_text(*, pdf_path: Path) -> str:
    """Extract layout text from all pages of a PDF.

    Args:
        pdf_path: Path to the PDF to inspect.
    Returns:
        Concatenated text from all pages.
    """

    reader = PdfReader(str(pdf_path))
    pages = [
        page.extract_text(extraction_mode="layout") or "" for page in reader.pages
    ]
    return "\n".join(pages)


def _normalize_text(*, text: str) -> str:
    """Normalize PDF text for substring checks.

    Args:
        text: Raw extracted text.
    Returns:
        Text with collapsed whitespace.
    """

    return re.sub(r"\s+", " ", text).strip()


def _run_checks(*, text: str, checks: Iterable[TextCheck]) -> List[str]:
    """Evaluate all checks against the provided text."""

    failures: List[str] = []
    for check in checks:
        failures.extend(check.evaluate(text=text))
    return failures


def main() -> None:
    """Run spacing checks against output/section-135.pdf.

    Example:
        >>> main()  # doctest: +SKIP
    """

    pdf_path = Path("output/section-135.pdf")
    text = _normalize_text(text=_extract_layout_text(pdf_path=pdf_path))
    checks = [
        TextCheck(
            label="Small caps comma spacing",
            must_contain="INNOCENT, AND IT SHALL",
            must_not_contain="INNOCENT,AND IT SHALL",
        ),
        TextCheck(
            label="Hyphen spacing (forty-four)",
            must_contain="forty-four",
            must_not_contain="forty- four",
        ),
        TextCheck(
            label="Hyphen spacing (thirty-eight)",
            must_contain="thirty-eight",
            must_not_contain="thirty- eight",
        ),
        TextCheck(
            label="Superscript prefix a",
            must_contain="been afaithful",
            must_not_contain="been a faithful",
        ),
        TextCheck(
            label="Superscript prefix b",
            must_contain="made bclean",
            must_not_contain="made b clean",
        ),
        TextCheck(
            label="Superscript prefix c",
            must_contain="cjudgment",
            must_not_contain="c judgment",
        ),
    ]
    failures = _run_checks(text=text, checks=checks)
    if failures:
        failure_text = "\n".join(failures)
        raise AssertionError(f"PDF spacing checks failed:\\n{failure_text}")
    print("PDF spacing checks passed.")


if __name__ == "__main__":
    main()
