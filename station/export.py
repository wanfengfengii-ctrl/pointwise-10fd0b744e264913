import json
from itertools import pairwise

from plan.catalog import get_task
from plan.layout import segment_for_slot
from plan.rationals import rational_text
from .interval_pieces import V2_FIELDS, V2_VERSION
from .pieces import V1_FIELDS, V1_VERSION
from .storage import get_interval_piece, get_piece


def export_segment(db, piece_id):
    piece = get_piece(db, piece_id)
    values = (
        V1_VERSION, piece.origin, piece.piece_id, piece.task_id,
        piece.slot, piece.revision_id, rational_text(piece.first),
        rational_text(piece.last), piece.crossings,
    )
    payload = dict(zip(V1_FIELDS, values, strict=True))
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def export_interval_segment(db, piece_id):
    piece = get_interval_piece(db, piece_id)
    layout = segment_for_slot(get_task(db, piece.task_id).segments, piece.slot)
    boundary_beat = layout.beats[-1] if piece.slot == 1 else layout.beats[0]
    intervals = {beat: (lo, hi) for beat, lo, hi in piece.intervals}
    lo, hi = intervals[boundary_beat]
    values = (
        V2_VERSION, piece.origin, piece.piece_id, piece.task_id, piece.slot,
        piece.revision_id, boundary_beat,
        [rational_text(lo), rational_text(hi)],
        [[before, after] for before, after in pairwise(layout.beats)],
        [
            [rational_text(entry.lo), rational_text(entry.hi), entry.lo_open, entry.hi_open, entry.count]
            for entry in piece.relation
        ],
    )
    payload = dict(zip(V2_FIELDS, values, strict=True))
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
