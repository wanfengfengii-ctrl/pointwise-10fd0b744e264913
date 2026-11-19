from ledger.query import get_revision
from plan.catalog import get_task
from plan.layout import segment_for_slot
from plan.rationals import parse_rational
from .crossings import count_crossings
from .intervals import segment_relation
from .limits import check_local_limits
from .storage import save_interval_piece, save_piece


MAX_INTERVAL_BEATS = 8


def freeze_segment(db, revision_id):
    revision = get_revision(db, revision_id)
    protocol = get_task(db, revision.task_id).protocol
    values = tuple(value for _, value in revision.samples)
    check_local_limits(values, protocol.max_change)
    crossings = count_crossings(values, protocol.threshold)
    return save_piece(db, revision, values[0], values[-1], crossings)


def validate_intervals(layout, revision, intervals):
    if not 1 <= len(layout.beats) <= MAX_INTERVAL_BEATS:
        raise ValueError('interval segments are limited to 1..8 beats')
    readings = dict(revision.samples)
    try:
        entries = iter(intervals)
    except TypeError as error:
        raise ValueError('intervals must be an iterable of beat, lo, hi triples') from error
    spans = {}
    for entry in entries:
        try:
            beat, lo, hi = entry
        except (TypeError, ValueError) as error:
            raise ValueError('an interval must contain one beat and two endpoints') from error
        if type(beat) is not int or beat not in readings:
            raise ValueError('interval beat falls outside the segment layout')
        if beat in spans:
            raise ValueError('duplicate interval beat')
        lo = parse_rational(lo)
        hi = parse_rational(hi)
        if not lo <= readings[beat] <= hi:
            raise ValueError('interval must contain the original reading')
        spans[beat] = (lo, hi)
    if spans.keys() != readings.keys():
        raise ValueError('intervals must cover every planned beat')
    return tuple(spans[beat] for beat in layout.beats)


def freeze_interval_segment(db, revision_id, intervals):
    revision = get_revision(db, revision_id)
    task = get_task(db, revision.task_id)
    layout = segment_for_slot(task.segments, revision.slot)
    spans = validate_intervals(layout, revision, intervals)
    relation = segment_relation(layout.slot, spans, task.protocol)
    return save_interval_piece(db, revision, spans, relation)
