from .interval_join import reachable_counts
from .join import evaluate_seam, total_crossings
from .selection import select_interval_pieces, select_pieces
from .storage import save_interval_review, save_review


def issue_review(db, task_id, front_id, back_id, *, before_commit=None):
    selection = select_pieces(db, task_id, front_id, back_id)
    front = selection.front.piece
    back = selection.back.piece
    seam = evaluate_seam(selection.task.protocol, front, back)
    total = total_crossings(front, back, seam)
    return save_review(db, selection, seam, total, before_commit=before_commit)


def issue_interval_review(db, task_id, front_id, back_id, *, before_commit=None):
    selection = select_interval_pieces(db, task_id, front_id, back_id)
    protocol = selection.task.protocol
    counts = reachable_counts(
        selection.front.piece.relation, selection.back.piece.relation,
        protocol.threshold, protocol.max_change,
    )
    return save_interval_review(db, selection, counts, before_commit=before_commit)
