import json

from database import is_key
from plan.protocols import require_label
from plan.rationals import parse_rational, rational_text
from station.interval_pieces import V2_FIELDS, V2_VERSION, IntervalPiece
from station.intervals import RelationEntry, make_interval
from station.pieces import StationPiece, V1_FIELDS, V1_VERSION


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'duplicate station piece field: {key}')
        obj[key] = value
    return obj


def _wire_rational(raw):
    if not isinstance(raw, str):
        raise ValueError('station endpoints must be rational strings')
    value = parse_rational(raw)
    if rational_text(value) != raw:
        raise ValueError('station endpoints must use reduced numerator/denominator text')
    return value


def decode_v1(payload):
    if not isinstance(payload, bytes):
        raise ValueError('a station piece must be UTF-8 JSON bytes')
    try:
        data = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid station piece JSON') from error
    if type(data) is not dict or data.keys() != set(V1_FIELDS):
        raise ValueError('unexpected V1 station piece fields')
    if type(data['version']) is not int or data['version'] != V1_VERSION:
        raise ValueError('unsupported station piece version')
    require_label(data['origin'], 'station origin')
    for field in ('piece_id', 'task_id', 'revision_id'):
        if not is_key(data[field]):
            raise ValueError(f'invalid station piece {field}')
    if type(data['slot']) is not int or data['slot'] not in (1, 2):
        raise ValueError('invalid station piece slot')
    if type(data['crossings']) is not int or data['crossings'] < 0:
        raise ValueError('invalid station crossing count')
    return StationPiece(
        data['origin'], data['piece_id'], data['task_id'], data['slot'],
        data['revision_id'], _wire_rational(data['first']),
        _wire_rational(data['last']), data['crossings'],
    )


def _wire_closed_interval(raw):
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError('a boundary interval must be a pair of rational strings')
    lo, hi = (_wire_rational(part) for part in raw)
    if lo > hi:
        raise ValueError('boundary interval endpoints are out of order')
    return (lo, hi)


def _wire_counted_pairs(raw):
    if not isinstance(raw, list):
        raise ValueError('counted pairs must be a list')
    pairs = []
    for entry in raw:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError('a counted pair must contain two beats')
        before, after = entry
        if type(before) is not int or type(after) is not int:
            raise ValueError('counted pair beats must be integers')
        pairs.append((before, after))
    return tuple(pairs)


def _wire_relation(raw):
    if not isinstance(raw, list):
        raise ValueError('an interval relation must be a list')
    relation = []
    for entry in raw:
        if not isinstance(entry, list) or len(entry) != 5:
            raise ValueError('a relation entry must hold lo, hi, openness and count')
        lo_raw, hi_raw, lo_open, hi_open, count = entry
        lo = _wire_rational(lo_raw)
        hi = _wire_rational(hi_raw)
        if type(lo_open) is not bool or type(hi_open) is not bool:
            raise ValueError('relation openness flags must be booleans')
        if type(count) is not int or count < 0:
            raise ValueError('relation count must be a nonnegative integer')
        if make_interval(lo, hi, lo_open, hi_open) is None:
            raise ValueError('a relation entry describes an empty interval')
        relation.append(RelationEntry(lo, hi, lo_open, hi_open, count))
    return tuple(relation)


def decode_v2(payload):
    if not isinstance(payload, bytes):
        raise ValueError('an interval piece must be UTF-8 JSON bytes')
    try:
        data = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid interval piece JSON') from error
    if type(data) is not dict or data.keys() != set(V2_FIELDS):
        raise ValueError('unexpected V2 interval piece fields')
    if type(data['version']) is not int or data['version'] != V2_VERSION:
        raise ValueError('unsupported interval piece version')
    require_label(data['origin'], 'station origin')
    for field in ('piece_id', 'task_id', 'revision_id'):
        if not is_key(data[field]):
            raise ValueError(f'invalid interval piece {field}')
    if type(data['slot']) is not int or data['slot'] not in (1, 2):
        raise ValueError('invalid interval piece slot')
    if type(data['boundary_beat']) is not int:
        raise ValueError('invalid interval piece boundary beat')
    return IntervalPiece(
        data['origin'], data['piece_id'], data['task_id'], data['slot'],
        data['revision_id'], data['boundary_beat'],
        _wire_closed_interval(data['boundary_interval']),
        _wire_counted_pairs(data['counted_pairs']),
        _wire_relation(data['relation']),
    )
