from dataclasses import dataclass

from database import require_key, write_transaction
from station.interval_pieces import IntervalPiece
from station.pieces import StationPiece
from .decode import decode_v1, decode_v2
from .eligibility import check_eligibility, check_interval_eligibility
from .receipts import (
    AcceptanceReceipt, get_interval_receipt, get_receipt,
    initialize_interval_receipts, initialize_receipts, insert_interval_receipt,
    insert_receipt,
)


@dataclass(frozen=True)
class AcceptedPiece:
    acceptance_id: int
    piece: StationPiece
    payload: bytes
    receipt: AcceptanceReceipt


@dataclass(frozen=True)
class AcceptedIntervalPiece:
    acceptance_id: int
    piece: IntervalPiece
    payload: bytes
    receipt: AcceptanceReceipt


def initialize_intake(db):
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS accepted_pieces (
                acceptance_id INTEGER PRIMARY KEY,
                origin TEXT NOT NULL,
                piece_id INTEGER NOT NULL,
                payload BLOB NOT NULL,
                UNIQUE (origin, piece_id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS accepted_interval_pieces (
                acceptance_id INTEGER PRIMARY KEY,
                origin TEXT NOT NULL,
                piece_id INTEGER NOT NULL,
                payload BLOB NOT NULL,
                UNIQUE (origin, piece_id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS acceptance_sequence (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                next_id INTEGER NOT NULL
            )
        ''')
        initialize_receipts(db)
        initialize_interval_receipts(db)


def allocate_acceptance_id(db):
    """Draw the next acceptance id from the sequence shared by V1 and V2."""
    row = db.execute('SELECT next_id FROM acceptance_sequence WHERE singleton = 1').fetchone()
    if row is None:
        v1 = db.execute('SELECT COALESCE(MAX(acceptance_id), 0) FROM accepted_pieces').fetchone()[0]
        v2 = db.execute('SELECT COALESCE(MAX(acceptance_id), 0) FROM accepted_interval_pieces').fetchone()[0]
        next_id = max(v1, v2) + 1
        db.execute('INSERT INTO acceptance_sequence (singleton, next_id) VALUES (1, ?)', (next_id,))
    else:
        next_id = row[0]
    db.execute('UPDATE acceptance_sequence SET next_id = ? WHERE singleton = 1', (next_id + 1,))
    return next_id


def accept_segment(db, payload):
    piece = decode_v1(payload)
    check_eligibility(db, piece)
    with write_transaction(db):
        previous = db.execute('''
            SELECT acceptance_id, payload FROM accepted_pieces
            WHERE origin = ? AND piece_id = ?
        ''', (piece.origin, piece.piece_id)).fetchone()
        if previous is not None:
            acceptance_id, original = previous
            if piece != decode_v1(original):
                raise ValueError('station piece identity already has different content')
            return acceptance_id

        acceptance_id = allocate_acceptance_id(db)
        db.execute('''
            INSERT INTO accepted_pieces (acceptance_id, origin, piece_id, payload)
            VALUES (?, ?, ?, ?)
        ''', (acceptance_id, piece.origin, piece.piece_id, payload))
        insert_receipt(db, acceptance_id, piece.origin, piece.piece_id)
    return acceptance_id


def accept_interval_segment(db, payload):
    piece = decode_v2(payload)
    check_interval_eligibility(db, piece)
    with write_transaction(db):
        previous = db.execute('''
            SELECT acceptance_id, payload FROM accepted_interval_pieces
            WHERE origin = ? AND piece_id = ?
        ''', (piece.origin, piece.piece_id)).fetchone()
        if previous is not None:
            acceptance_id, original = previous
            if piece != decode_v2(original):
                raise ValueError('interval piece identity already has different content')
            return acceptance_id

        acceptance_id = allocate_acceptance_id(db)
        db.execute('''
            INSERT INTO accepted_interval_pieces (acceptance_id, origin, piece_id, payload)
            VALUES (?, ?, ?, ?)
        ''', (acceptance_id, piece.origin, piece.piece_id, payload))
        insert_interval_receipt(db, acceptance_id, piece.origin, piece.piece_id)
    return acceptance_id


def get_accepted_piece(db, acceptance_id):
    require_key(acceptance_id)
    row = db.execute('''
        SELECT payload FROM accepted_pieces WHERE acceptance_id = ?
    ''', (acceptance_id,)).fetchone()
    if row is None:
        raise KeyError(acceptance_id)
    payload = row[0]
    return AcceptedPiece(acceptance_id, decode_v1(payload), payload, get_receipt(db, acceptance_id))


def get_accepted_interval_piece(db, acceptance_id):
    require_key(acceptance_id)
    row = db.execute('''
        SELECT payload FROM accepted_interval_pieces WHERE acceptance_id = ?
    ''', (acceptance_id,)).fetchone()
    if row is None:
        v1 = db.execute('''
            SELECT 1 FROM accepted_pieces WHERE acceptance_id = ?
        ''', (acceptance_id,)).fetchone()
        if v1 is not None:
            raise ValueError('acceptance id belongs to a V1 station piece')
        raise KeyError(acceptance_id)
    payload = row[0]
    return AcceptedIntervalPiece(
        acceptance_id, decode_v2(payload), payload, get_interval_receipt(db, acceptance_id),
    )
