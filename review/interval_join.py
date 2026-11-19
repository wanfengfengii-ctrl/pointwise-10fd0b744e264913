"""Combine two V2 boundary relations into reachable whole-run alarm counts.

The center only sees the two accepted boundary relations plus the task
protocol.  A whole-run trajectory exists exactly when some front boundary
value x and back boundary value y satisfy |x - y| <= max_change; the seam
alarm is 1 only when x < threshold <= y and is accounted once, here, never
inside a piece.
"""
from station.intervals import clip_above, clip_below, pair_within


def _as_interval(entry):
    return (entry.lo, entry.hi, entry.lo_open, entry.hi_open)


def seam_options(front_entry, back_entry, threshold, max_change):
    """Seam alarm values compatible with some feasible boundary pair."""
    front = _as_interval(front_entry)
    back = _as_interval(back_entry)
    if not pair_within(front, back, max_change):
        return ()
    options = []
    front_below = clip_below(front, threshold)
    back_above = clip_above(back, threshold)
    if (front_below is not None and back_above is not None
            and pair_within(front_below, back_above, max_change)):
        options.append(1)
    front_above = clip_above(front, threshold)
    back_below = clip_below(back, threshold)
    if ((front_above is not None and pair_within(front_above, back, max_change))
            or (back_below is not None and pair_within(front, back_below, max_change))):
        options.append(0)
    return tuple(options)


def reachable_counts(front_relation, back_relation, threshold, max_change):
    """Ascending whole-run alarm counts reachable over both relations."""
    totals = set()
    for front_entry in front_relation:
        for back_entry in back_relation:
            for seam in seam_options(front_entry, back_entry, threshold, max_change):
                totals.add(front_entry.count + back_entry.count + seam)
    return sorted(totals)
