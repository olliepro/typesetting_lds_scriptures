"""Custom flowables used in scripture layout."""

from __future__ import annotations

from typing import Sequence

from reportlab.lib import colors
from reportlab.platypus import Flowable, Paragraph


def _wrap_height(*, child: Flowable, width: float) -> float:
    """Return the wrapped height of a flowable.

    Args:
        child: Flowable to measure.
        width: Available width.
    Returns:
        Measured height in points.
    """

    _, height = child.wrap(width, 10_000)
    return height


class StackedFlowable(Flowable):
    """Stack child flowables vertically as a single unbreakable block."""

    def __init__(self, content: Sequence[Flowable], logical_lines: int = 1) -> None:
        super().__init__()
        self.content = list(content)
        self.width = 0.0
        self.height = 0.0
        self.logical_lines = max(1, logical_lines)
        self.book_title_group = False

    def wrap(self, aW: float, aH: float) -> tuple[float, float]:
        """Measure total height for the stacked content.

        Args:
            aW: Available width for wrapping.
            aH: Available height for wrapping.
        Returns:
            Tuple of (width, height).
        """

        self.width = aW
        heights = [_wrap_height(child=child, width=aW) for child in self.content]
        self.height = sum(heights)
        return aW, self.height

    def draw(self) -> None:
        """Draw child flowables from top to bottom."""

        y = self.height
        for child in self.content:
            _, height = child.wrap(self.width, self.height)
            y -= height
            child.drawOn(self.canv, 0, y)


class SectionTitleFlowable(Flowable):
    """Render a section title with a centered bar above the text."""

    def __init__(
        self,
        *,
        paragraph: Paragraph,
        text_width: float,
        line_gap: float,
        line_thickness: float,
        line_color: colors.Color,
    ) -> None:
        super().__init__()
        self.paragraph = paragraph
        self.text_width = text_width
        self.line_gap = line_gap
        self.line_thickness = line_thickness
        self.line_color = line_color
        self.width = 0.0
        self.height = 0.0
        self._para_height = 0.0
        self.spaceBefore = getattr(paragraph, "spaceBefore", 0.0)
        self.spaceAfter = getattr(paragraph, "spaceAfter", 0.0)

    def wrap(self, aW: float, aH: float) -> tuple[float, float]:
        """Measure total height for the bar + title text.

        Args:
            aW: Available width for wrapping.
            aH: Available height for wrapping.
        Returns:
            Tuple of (width, height).
        """

        self.width, self._para_height = self.paragraph.wrap(aW, aH)
        self.height = self._para_height + self.line_gap + self.line_thickness
        return self.width, self.height

    def draw(self) -> None:
        """Draw the bar and the title paragraph."""

        line_width = min(self.text_width, self.width)
        x = max(0.0, (self.width - line_width) / 2)
        y = self._para_height + self.line_gap + (self.line_thickness / 2)
        self.canv.saveState()
        self.canv.setStrokeColor(self.line_color)
        self.canv.setLineWidth(self.line_thickness)
        self.canv.line(x, y, x + line_width, y)
        self.paragraph.drawOn(self.canv, 0, 0)
        self.canv.restoreState()
