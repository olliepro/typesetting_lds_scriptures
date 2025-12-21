"""Shared constants for PDF layout and text processing."""

from __future__ import annotations

import os

HAIR_SPACE = "\u200a"
DASH_CHARS = ("-", "\u2013", "\u2014")
EPSILON = 1e-4
DEBUG_PAGINATION = os.getenv("DEBUG_PAGINATION", "0") not in {
    "",
    "0",
    "false",
    "False",
}
