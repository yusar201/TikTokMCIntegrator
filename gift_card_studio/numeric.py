"""Numeric helpers that must behave identically in Python and JavaScript.

Python and JS disagree on how to round a value sitting exactly on a half unit:

    Python  round(2.5) == 2      # banker's rounding, ties to even
    JS      Math.round(2.5) === 3  # ties toward +infinity

Every Gift Card Studio module with a JS mirror shares geometry and timing
numbers across that boundary, so any tie-valued coordinate, opacity, or frame
timestamp would serialize differently on each side. This was not theoretical: a
cross-fade at opacity ``0.0025`` rendered as ``0.002`` in Python and ``0.003`` in
JS, which the frame-parity suite caught as a byte mismatch.

Use ``js_round`` anywhere a number crosses into shared output — SVG attributes,
frame timestamps, loop durations. Plain ``round`` is fine for values that never
leave Python.
"""
from __future__ import annotations

import math


def js_round(value) -> int:
    """Round half up (toward +infinity), matching JS ``Math.round``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number != number or number in (float("inf"), float("-inf")):
        return 0
    return math.floor(number + 0.5)
