import json

from database import require_key, write_transaction
from plan.rationals import parse_rational, rational_text
from .interval_pieces import RelationEntry, StoredIntervalPiece
from .pieces import StationPiece


def initialize_station(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS station_pieces (
            piece_id INTEGER PRIMARY KEY,
            origin TEXT NOT NULL,
            task_id INTEGER NOT NULL REFERENCES task_catalog (task_id),
            slot INTEGER NOT NULL CHECK (slot IN (1, 2)),
            revision_id INTEGER NOT NULL REFERENCES reading_revisions (revision_id),
            first_value TEXT NOT NULL,
            last_value TEXT NOT NULL,
            crossings INTEGER NOT NULL CHECK (crossings >= 0)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS interval_pieces (
            piece_id INTEGER PRIMARY KEY,
            origin TEXT NOT NULL,
            task_id INTEGER NOT NULL REFERENCES task_catalog (task_id),
            slot INTEGER NOT NULL CHECK (slot IN (1, 2)),
            revision_id INTEGER NOT NULL REFERENCES reading_revisions (revision_id),
            intervals TEXT NOT NULL,
            relation TEXT NOT NULL
        )
    ''')


def save_piece(db, revision, first, last, crossings):
    fields = (
        revision.origin, revision.task_id, revision.slot, revision.revision_id,
        rational_text(first), rational_text(last), crossings,
    )
    with write_transaction(db):
        cursor = db.execute('''
            INSERT INTO station_pieces
                (origin, task_id, slot, revision_id, first_value, last_value, crossings)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', fields)
        piece_id = cursor.lastrowid
    return piece_id


def get_piece(db, piece_id):
    require_key(piece_id)
    row = db.execute('''
        SELECT origin, task_id, slot, revision_id, first_value, last_value, crossings
        FROM station_pieces WHERE piece_id = ?
    ''', (piece_id,)).fetchone()
    if row is None:
        raise KeyError(piece_id)
    origin, task_id, slot, revision_id, first, last, crossings = row
    return StationPiece(
        origin, piece_id, task_id, slot, revision_id,
        parse_rational(first), parse_rational(last), crossings,
    )


def _relation_text(relation):
    return [
        [rational_text(entry.lo), rational_text(entry.hi), entry.lo_open, entry.hi_open, entry.count]
        for entry in relation
    ]


def _parse_relation(raw):
    return tuple(
        RelationEntry(parse_rational(lo), parse_rational(hi), lo_open, hi_open, count)
        for lo, hi, lo_open, hi_open, count in raw
    )


def save_interval_piece(db, revision, spans, relation):
    intervals = tuple(
        (beat, lo, hi)
        for (beat, _), (lo, hi) in zip(revision.samples, spans, strict=True)
    )
    stored_intervals = [
        [beat, rational_text(lo), rational_text(hi)] for beat, lo, hi in intervals
    ]
    fields = (
        revision.origin, revision.task_id, revision.slot, revision.revision_id,
        json.dumps(stored_intervals, separators=(',', ':')),
        json.dumps(_relation_text(relation), separators=(',', ':')),
    )
    with write_transaction(db):
        cursor = db.execute('''
            INSERT INTO interval_pieces
                (origin, task_id, slot, revision_id, intervals, relation)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', fields)
        piece_id = cursor.lastrowid
    return piece_id


def get_interval_piece(db, piece_id):
    require_key(piece_id)
    row = db.execute('''
        SELECT origin, task_id, slot, revision_id, intervals, relation
        FROM interval_pieces WHERE piece_id = ?
    ''', (piece_id,)).fetchone()
    if row is None:
        raise KeyError(piece_id)
    origin, task_id, slot, revision_id, intervals, relation = row
    stored_intervals = tuple(
        (beat, parse_rational(lo), parse_rational(hi))
        for beat, lo, hi in json.loads(intervals)
    )
    return StoredIntervalPiece(
        origin, piece_id, task_id, slot, revision_id,
        stored_intervals, _parse_relation(json.loads(relation)),
    )
