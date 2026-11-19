from itertools import pairwise

from plan.catalog import get_task
from plan.layout import segment_for_slot


def check_eligibility(db, piece):
    try:
        task = get_task(db, piece.task_id)
    except KeyError as error:
        raise ValueError('station piece refers to an unknown task') from error
    layout = segment_for_slot(task.segments, piece.slot)
    if piece.origin != layout.origin:
        raise ValueError('station piece origin does not own this segment')
    beat_count = len(layout.beats)
    if piece.crossings > beat_count // 2:
        raise ValueError('station crossing count exceeds the segment capacity')
    if beat_count == 1 and piece.first != piece.last:
        raise ValueError('a single-beat piece requires identical endpoints')


def check_interval_eligibility(db, piece):
    try:
        task = get_task(db, piece.task_id)
    except KeyError as error:
        raise ValueError('interval piece refers to an unknown task') from error
    layout = segment_for_slot(task.segments, piece.slot)
    if piece.origin != layout.origin:
        raise ValueError('interval piece origin does not own this segment')
    beats = layout.beats
    if not 1 <= len(beats) <= 8:
        raise ValueError('interval piece segment length outside 1..8')
    boundary = beats[-1] if piece.slot == 1 else beats[0]
    if piece.boundary_beat != boundary:
        raise ValueError('interval piece boundary does not match the segment seam')
    if piece.counted_pairs != tuple(pairwise(beats)):
        raise ValueError('interval piece counted pairs do not match the segment')
    lo, hi = piece.boundary_interval
    capacity = len(beats) // 2
    for entry in piece.relation:
        if entry.lo < lo or entry.hi > hi:
            raise ValueError('interval relation escapes the boundary interval')
        if entry.count > capacity:
            raise ValueError('interval relation count exceeds the segment capacity')
