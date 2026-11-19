"""Exact interval algebra and boundary feasibility relations for V2 pieces.

A boundary relation summarizes one frozen segment for the joint review: for
each value of the seam-side boundary variable it lists the internal alarm
counts that remain achievable inside the segment.  Intervals carry open and
closed flags so the split at the alarm threshold stays exact; endpoints are
always Fraction instances.
"""
from fractions import Fraction
from typing import NamedTuple


BELOW = 0
ABOVE = 1


class RelationEntry(NamedTuple):
    """Boundary values in [lo, hi] (flags mark open ends) allow `count` alarms."""
    lo: Fraction
    hi: Fraction
    lo_open: bool
    hi_open: bool
    count: int


def make_interval(lo, hi, lo_open=False, hi_open=False):
    if lo > hi or (lo == hi and (lo_open or hi_open)):
        return None
    return (lo, hi, lo_open, hi_open)


def offset_interval(interval, distance):
    lo, hi, lo_open, hi_open = interval
    return (lo - distance, hi + distance, lo_open, hi_open)


def intersect_closed(interval, lo, hi):
    start, end, start_open, end_open = interval
    if start < lo:
        start, start_open = lo, False
    if end > hi:
        end, end_open = hi, False
    return make_interval(start, end, start_open, end_open)


def clip_below(interval, threshold):
    """Keep only values strictly below the threshold."""
    lo, hi, lo_open, hi_open = interval
    if lo >= threshold:
        return None
    if hi < threshold:
        return interval
    return make_interval(lo, threshold, lo_open, True)


def clip_above(interval, threshold):
    """Keep only values at or above the threshold."""
    lo, hi, lo_open, hi_open = interval
    if hi < threshold:
        return None
    if lo >= threshold:
        return interval
    return make_interval(threshold, hi, False, hi_open)


def merge_intervals(intervals):
    merged = []
    for interval in sorted(intervals, key=lambda iv: (iv[0], iv[2])):
        if merged:
            lo, hi, lo_open, hi_open = merged[-1]
            touches = interval[0] < hi or (
                interval[0] == hi and not (interval[2] and hi_open)
            )
            if touches:
                if interval[1] > hi:
                    merged[-1] = (lo, interval[1], lo_open, interval[3])
                elif interval[1] == hi:
                    merged[-1] = (lo, hi, lo_open, hi_open and interval[3])
                continue
        merged.append(interval)
    return merged


def pair_within(first, second, distance):
    """Whether some x in first and y in second satisfy |x - y| <= distance."""
    first_lo, first_hi, first_lo_open, first_hi_open = first
    second_lo, second_hi, second_lo_open, second_hi_open = second
    if first_lo > second_hi + distance or (
        first_lo == second_hi + distance and (first_lo_open or second_hi_open)
    ):
        return False
    if second_lo > first_hi + distance or (
        second_lo == first_hi + distance and (second_lo_open or first_hi_open)
    ):
        return False
    return True


def _crossed(before_sign, after_sign, upward):
    if upward:
        return before_sign == BELOW and after_sign == ABOVE
    return before_sign == ABOVE and after_sign == BELOW


def boundary_relation(spans, threshold, max_change, upward):
    """Achievable internal alarm counts per value of the last span's beat.

    `spans` holds closed (lo, hi) bounds in processing order.  Alarms are
    counted between consecutive processed beats; `upward` selects whether an
    alarm is a rise across the threshold (front segments) or, after
    reversal, a drop (back segments).  Returns a canonical tuple of
    RelationEntry; an empty tuple means no feasible trajectory exists.
    """
    lo, hi = spans[0]
    states = {}
    for sign, clip in ((BELOW, clip_below), (ABOVE, clip_above)):
        part = clip((lo, hi, False, False), threshold)
        if part is not None:
            states[0, sign] = [part]
    for lo, hi in spans[1:]:
        following = {}
        for (count, sign), union in states.items():
            for interval in union:
                reach = intersect_closed(offset_interval(interval, max_change), lo, hi)
                if reach is None:
                    continue
                for after_sign, clip in ((BELOW, clip_below), (ABOVE, clip_above)):
                    part = clip(reach, threshold)
                    if part is None:
                        continue
                    key = (count + int(_crossed(sign, after_sign, upward)), after_sign)
                    following.setdefault(key, []).append(part)
        states = {key: merge_intervals(union) for key, union in following.items()}
    by_count = {}
    for (count, sign), union in states.items():
        by_count.setdefault(count, []).extend(union)
    entries = []
    for count, union in by_count.items():
        for lo, hi, lo_open, hi_open in merge_intervals(union):
            entries.append(RelationEntry(lo, hi, lo_open, hi_open, count))
    entries.sort()
    return tuple(entries)


def segment_relation(slot, spans, protocol):
    """Boundary relation for the seam-side beat of a frozen segment."""
    if slot == 1:
        return boundary_relation(spans, protocol.threshold, protocol.max_change, True)
    return boundary_relation(tuple(reversed(spans)), protocol.threshold, protocol.max_change, False)
