from dataclasses import dataclass
import json
from typing import NamedTuple

from plan.rationals import parse_rational
from .join import SeamResult
from .storage import ReviewReceipt, read_interval_review_row, read_review_rows


@dataclass(frozen=True)
class ReviewResult:
    report_id: int
    task_id: int
    front_id: int
    back_id: int
    front_crossings: int
    back_crossings: int
    seam: SeamResult
    total_crossings: int
    receipt: ReviewReceipt


def get_review(db, report_id):
    fields, receipt = read_review_rows(db, report_id)
    task_id, front_id, back_id, front_count, back_count, before, after, change, seam_count, total = fields
    seam = SeamResult(parse_rational(before), parse_rational(after), parse_rational(change), seam_count)
    return ReviewResult(
        report_id, task_id, front_id, back_id, front_count, back_count, seam, total, receipt,
    )


class IntervalSource(NamedTuple):
    origin: str
    piece_id: int
    revision_id: int


@dataclass(frozen=True)
class IntervalReviewResult:
    report_id: int
    task_id: int
    front_id: int
    back_id: int
    front_source: IntervalSource
    back_source: IntervalSource
    reachable_counts: list
    receipt: ReviewReceipt


def get_interval_review(db, report_id):
    fields, receipt = read_interval_review_row(db, report_id)
    (task_id, front_id, back_id, front_origin, front_piece, front_revision,
     back_origin, back_piece, back_revision, counts) = fields
    return IntervalReviewResult(
        report_id, task_id, front_id, back_id,
        IntervalSource(front_origin, front_piece, front_revision),
        IntervalSource(back_origin, back_piece, back_revision),
        list(json.loads(counts)), receipt,
    )
