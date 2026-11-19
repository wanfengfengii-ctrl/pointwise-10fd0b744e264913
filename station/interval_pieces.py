"""Wire and storage shapes for V2 interval pieces.

The exported evidence fixes the boundary variable used by the joint review
(the seam-side beat: the last beat for front segments, the first beat for
back segments) together with its frozen closed interval.  `counted_pairs`
lists the in-segment adjacent pairs whose alarms are already accounted for
in the relation counts; the seam alarm is never accounted inside a piece.
Each relation entry `[lo, hi, lo_open, hi_open, count]` states that `count`
internal alarms remain achievable while the boundary variable stays inside
the described interval.  Per-beat original readings and interior beat
intervals stay at the station.
"""
from dataclasses import dataclass
from fractions import Fraction

from .intervals import RelationEntry


V2_VERSION = 2
V2_FIELDS = (
    'version', 'origin', 'piece_id', 'task_id', 'slot', 'revision_id',
    'boundary_beat', 'boundary_interval', 'counted_pairs', 'relation',
)


@dataclass(frozen=True)
class IntervalPiece:
    origin: str
    piece_id: int
    task_id: int
    slot: int
    revision_id: int
    boundary_beat: int
    boundary_interval: tuple[Fraction, Fraction]
    counted_pairs: tuple[tuple[int, int], ...]
    relation: tuple[RelationEntry, ...]


@dataclass(frozen=True)
class StoredIntervalPiece:
    origin: str
    piece_id: int
    task_id: int
    slot: int
    revision_id: int
    intervals: tuple[tuple[int, Fraction, Fraction], ...]
    relation: tuple[RelationEntry, ...]
