"""Spintax parser: {a|b|c} and nested {a|{b|c}} are supported."""
from __future__ import annotations

import random
import re

_PATTERN = re.compile(r"\{([^{}]*)\}")


def spin(text: str) -> str:
    """Resolve all {a|b|c} groups randomly. Supports nesting via iterative expansion."""
    if not text:
        return text
    prev = None
    current = text
    # Iteratively resolve innermost braces until none remain or nothing changes.
    while prev != current:
        prev = current

        def _pick(match: re.Match[str]) -> str:
            options = match.group(1).split("|")
            return random.choice(options)

        current = _PATTERN.sub(_pick, current)
    return current
