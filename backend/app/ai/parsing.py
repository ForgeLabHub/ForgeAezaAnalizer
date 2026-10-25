"""Tolerant parsing of model output.

Small local models occasionally stop mid-object when they hit the token limit,
producing JSON that is well-formed up to the cut and then truncated.  Rejecting
such a reply outright wastes the (slow, CPU-bound) generation, so this module
salvages the largest complete prefix instead.

Repair is deliberately conservative: it only closes strings, arrays and objects
that the model left open, and never invents keys or values.  If the result still
does not parse, the caller treats it as a failed generation.
"""

from __future__ import annotations

import json
import re

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?|\n?```\s*$")


def strip_code_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


def _safe_prefix(text: str) -> str:
    """Return the longest prefix that does not end inside a string literal."""

    in_string = False
    escaped = False
    last = 0
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
                last = index + 1
        else:
            if char == '"':
                in_string = True
            else:
                last = index + 1
    return text[:last]


def _close(text: str) -> str:
    """Append the closers needed to balance brackets and braces."""

    in_string = False
    escaped = False
    stack: list[str] = []
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif char == "]" and stack and stack[-1] == "[":
            stack.pop()
    repaired = text
    if in_string:
        repaired += '"'
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    return repaired


def parse_json(text: str) -> dict:
    """Parse model output, repairing a truncated object when necessary."""

    candidate = strip_code_fence(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass


    working = _safe_prefix(candidate)
    for _ in range(64):
        attempt = working.rstrip().rstrip(",")
        try:
            return json.loads(_close(attempt))
        except json.JSONDecodeError:
            if "," not in working:
                break
            working = working.rsplit(",", 1)[0]
    raise ValueError("ответ модели не удалось разобрать как JSON")
