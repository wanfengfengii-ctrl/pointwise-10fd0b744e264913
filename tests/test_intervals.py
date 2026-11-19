import itertools
import json
import random
import sqlite3
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from intake.registry import (
    accept_interval_segment, accept_segment, get_accepted_interval_piece,
    get_accepted_piece,
)
from ledger.ingest import record_segment
from review.history import get_interval_review
from review.issue import issue_interval_review
from station.export import export_interval_segment, export_segment
from station.freeze import freeze_interval_segment, freeze_segment
from station.storage import get_interval_piece
from tests.fixtures import EAST, WEST, FailBeforeCommit, LabCase


EXAMPLES = Path(__file__).resolve().parent.parent / 'examples' / 'interval_shift.json'


def changed_wire(wire, **updates):
    value = json.loads(wire)
    value.update(updates)
    return json.dumps(value).encode('utf-8')


class IntervalCase(LabCase):
    def interval_wire(self, db, task, slot, rows, parent_id=None):
        revision = record_segment(
            db, task, slot, [(beat, reading) for beat, reading, lo, hi in rows],
            parent_id=parent_id,
        )
        piece = freeze_interval_segment(
            db, revision, [(beat, lo, hi) for beat, reading, lo, hi in rows],
        )
        return revision, piece, export_interval_segment(db, piece)

    def offline_interval_accept(self, task, front_rows, back_rows):
        front = self.interval_wire(self.left, task, 1, front_rows)
        back = self.interval_wire(self.right, task, 2, back_rows)
        self.left.close()
        self.right.close()
        front_id = accept_interval_segment(self.center, front[2])
        back_id = accept_interval_segment(self.center, back[2])
        self.left = self.open_db(WEST)
        self.right = self.open_db(EAST)
        self.init_station(self.left, WEST)
        self.init_station(self.right, EAST)
        return (front[0], front[1], front_id), (back[0], back[1], back_id)

    def interval_piece_count(self, db):
        return db.execute('SELECT count(*) FROM interval_pieces').fetchone()[0]

    def interval_intake_counts(self):
        pieces = self.center.execute('SELECT count(*) FROM accepted_interval_pieces').fetchone()[0]
        receipts = self.center.execute('SELECT count(*) FROM interval_acceptance_receipts').fetchone()[0]
        return pieces, receipts

    def interval_review_counts(self, db=None):
        if db is None:
            db = self.center
        reports = db.execute('SELECT count(*) FROM interval_review_reports').fetchone()[0]
        receipts = db.execute('SELECT count(*) FROM interval_review_receipts').fetchone()[0]
        return reports, receipts


class TestIntervalFreeze(IntervalCase):
    def test_export_shape_and_stability(self):
        task = self.new_task((0, 1), (2,))
        revision, piece, wire = self.interval_wire(
            self.left, task, 1, [(0, 0, 0, 0), (1, 0, 0, 1)],
        )
        expected = (
            f'{{"version":2,"origin":"west","piece_id":{piece},"task_id":{task},'
            f'"slot":1,"revision_id":{revision},"boundary_beat":1,'
            f'"boundary_interval":["0/1","1/1"],"counted_pairs":[[0,1]],'
            f'"relation":[["0/1","1/1",false,true,0],["1/1","1/1",false,false,1]]}}'
        ).encode('utf-8')
        self.assertEqual(wire, expected)
        self.assertEqual(export_interval_segment(self.left, piece), wire)
        self.left.close()
        station = self.open_db(WEST)
        self.assertEqual(export_interval_segment(station, piece), wire)
        with self.assertRaises(KeyError):
            export_interval_segment(station, piece + 100)
        with self.assertRaises(KeyError):
            get_interval_piece(station, piece + 100)

        back_revision, back_piece, back_wire = self.interval_wire(
            self.right, task, 2, [(2, 2, 2, 2)],
        )
        back_expected = (
            f'{{"version":2,"origin":"east","piece_id":{back_piece},"task_id":{task},'
            f'"slot":2,"revision_id":{back_revision},"boundary_beat":2,'
            f'"boundary_interval":["2/1","2/1"],"counted_pairs":[],'
            f'"relation":[["2/1","2/1",false,false,0]]}}'
        ).encode('utf-8')
        self.assertEqual(back_wire, back_expected)

    def test_interior_intervals_stay_at_station(self):
        task = self.new_task((0, 1, 2), (3,))
        revision, piece, wire = self.interval_wire(
            self.left, task, 1, [(0, 0, 0, 0), (1, 1, 0, 2), (2, 0, 0, 0)],
        )
        self.assertNotIn('2/1', wire.decode('utf-8'))
        expected = (
            f'{{"version":2,"origin":"west","piece_id":{piece},"task_id":{task},'
            f'"slot":1,"revision_id":{revision},"boundary_beat":2,'
            f'"boundary_interval":["0/1","0/1"],"counted_pairs":[[0,1],[1,2]],'
            f'"relation":[["0/1","0/1",false,false,0],["0/1","0/1",false,false,1]]}}'
        ).encode('utf-8')
        self.assertEqual(wire, expected)
        stored = get_interval_piece(self.left, piece)
        self.assertEqual(
            stored.intervals,
            ((0, Fraction(0), Fraction(0)), (1, Fraction(0), Fraction(2)),
             (2, Fraction(0), Fraction(0))),
        )

    def test_unknown_revision(self):
        self.new_task()
        with self.assertRaises(KeyError):
            freeze_interval_segment(self.left, 100, [(0, 0, 0), (1, 0, 0)])
        self.assertEqual(self.interval_piece_count(self.left), 0)

    def test_interval_validation(self):
        task = self.new_task()
        revision = record_segment(self.left, task, 1, [(0, 0), (1, 1)])
        bad = (
            [(0, 0, 0)],
            [(0, 0, 0), (1, 0, 1), (1, 0, 1)],
            [(0, 0, 0), (2, 0, 1)],
            [(0, 0, 0), (True, 0, 1)],
            [(0, 0, 0), (1, 0.5, 1)],
            [(0, 0, 0), (1, None, 1)],
            [(0, 0, 0), (1, '1/0', 1)],
            [(0, 0, 0), (1, 2, 1)],
            [(0, 0, 0), (1, 0, '1/2')],
            [(0, 0, 0), (1, 1, 0)],
            None,
            [(0, 0)],
        )
        for intervals in bad:
            with self.subTest(intervals=intervals):
                with self.assertRaises(ValueError):
                    freeze_interval_segment(self.left, revision, intervals)
                self.assertEqual(self.interval_piece_count(self.left), 0)
        piece = freeze_interval_segment(self.left, revision, [(1, 1, 1), (0, 0, 0)])
        self.assertEqual(get_interval_piece(self.left, piece).revision_id, revision)
        self.assertEqual(self.interval_piece_count(self.left), 1)

    def test_segment_length_limit(self):
        task = self.new_task(tuple(range(9)), (9,))
        revision = record_segment(self.left, task, 1, [(beat, 0) for beat in range(9)])
        with self.assertRaises(ValueError):
            freeze_interval_segment(self.left, revision, [(beat, 0, 0) for beat in range(9)])
        self.assertEqual(self.interval_piece_count(self.left), 0)
        ok = self.new_task(tuple(range(8)), (8,), name='Eight')
        revision = record_segment(self.left, ok, 1, [(beat, 0) for beat in range(8)])
        freeze_interval_segment(self.left, revision, [(beat, 0, 0) for beat in range(8)])
        self.assertEqual(self.interval_piece_count(self.left), 1)

    def test_infeasible_segment_freezes_empty(self):
        task = self.new_task()
        _, piece, wire = self.interval_wire(self.left, task, 1, [(0, 0, 0, 0), (1, 3, 3, 3)])
        self.assertEqual(get_interval_piece(self.left, piece).relation, ())
        self.assertEqual(json.loads(wire)['relation'], [])

    def test_correction_revision_binding(self):
        task = self.new_task()
        original = record_segment(self.left, task, 1, [(0, 0), (1, 0)])
        corrected = record_segment(self.left, task, 1, [(0, 0), (1, 1)], parent_id=original)
        piece = freeze_interval_segment(self.left, corrected, [(0, 0, 0), (1, 1, 1)])
        wire = json.loads(export_interval_segment(self.left, piece))
        self.assertEqual(wire['revision_id'], corrected)
        other = freeze_interval_segment(self.left, original, [(0, 0, 0), (1, 0, 0)])
        self.assertNotEqual(piece, other)


class TestIntervalIntake(IntervalCase):
    def front_wire(self, task):
        return self.interval_wire(self.left, task, 1, [(0, 0, 0, 0), (1, 0, 0, 1)])[2]

    def test_replay_then_conflict(self):
        wire = self.front_wire(self.new_task())
        number = accept_interval_segment(self.center, wire)
        first = get_accepted_interval_piece(self.center, number)
        self.assertEqual(accept_interval_segment(self.center, wire), number)
        rearranged = dict(reversed(list(json.loads(wire).items())))
        equivalent = json.dumps(rearranged, indent=2).encode('utf-8')
        self.assertNotEqual(wire, equivalent)
        self.assertEqual(accept_interval_segment(self.center, equivalent), number)
        clash = changed_wire(wire, boundary_interval=['0/1', '2/1'])
        with self.assertRaises(ValueError):
            accept_interval_segment(self.center, clash)
        self.assertEqual(self.interval_intake_counts(), (1, 1))
        self.assertEqual(get_accepted_interval_piece(self.center, number), first)
        self.assertEqual(first.payload, wire)
        self.assertEqual(
            (first.receipt.acceptance_id, first.receipt.origin, first.receipt.piece_id),
            (number, WEST, first.piece.piece_id),
        )

    def test_rejections(self):
        task = self.new_task()
        wire = self.front_wire(task)
        v1 = export_segment(self.left, freeze_segment(
            self.left, record_segment(self.left, task, 1, [(0, 0), (1, 0)]),
        ))
        data = json.loads(wire)
        missing = dict(data)
        del missing['relation']
        variants = []
        for updates in (
            {'relation': [['0/1', '9/1', False, False, 0]]},
            {'relation': [['0/1', '1/1', False, False, 2]]},
            {'counted_pairs': [[0, 2]]},
            {'boundary_beat': 0},
            {'boundary_interval': ['1/1', '0/1']},
            {'boundary_interval': ['0/1', '2/2']},
            {'relation': [['0/1', '0/1', True, False, 0]]},
            {'relation': [['0/1', '1/1', 0, False, 0]]},
        ):
            changed = dict(data)
            changed.update(updates)
            variants.append(json.dumps(changed).encode('utf-8'))
        invalid = (
            b'{', b'\xff', v1,
            changed_wire(wire, version=1), changed_wire(wire, version=3),
            changed_wire(wire, version=True),
            json.dumps(missing).encode('utf-8'),
            changed_wire(wire, extra='field'),
            changed_wire(wire, task_id=task + 100), changed_wire(wire, origin=EAST),
            changed_wire(wire, slot=3), changed_wire(wire, piece_id=True),
            changed_wire(wire, boundary_beat=True), changed_wire(wire, revision_id=0),
            *variants,
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    accept_interval_segment(self.center, payload)
                self.assertEqual(self.interval_intake_counts(), (0, 0))
        valid = accept_interval_segment(self.center, wire)
        self.assertEqual(get_accepted_interval_piece(self.center, valid).payload, wire)
        self.assertEqual(self.interval_intake_counts(), (1, 1))

    def test_v1_v2_identities_never_mix(self):
        task = self.new_task()
        v1_revision = record_segment(self.left, task, 1, [(0, 0), (1, 0)])
        v1_wire = export_segment(self.left, freeze_segment(self.left, v1_revision))
        v2_revision, _, v2_wire = self.interval_wire(
            self.left, task, 1, [(0, 0, 0, 0), (1, 1, 1, 1)],
        )
        v1_id = accept_segment(self.center, v1_wire)
        v2_id = accept_interval_segment(self.center, v2_wire)
        self.assertNotEqual(v1_id, v2_id)
        with self.assertRaises(ValueError):
            get_accepted_interval_piece(self.center, v1_id)
        with self.assertRaises(KeyError):
            get_accepted_piece(self.center, v2_id)
        with self.assertRaises(KeyError):
            get_accepted_interval_piece(self.center, max(v1_id, v2_id) + 100)
        followup = accept_segment(self.center, export_segment(self.left, freeze_segment(
            self.left, record_segment(self.left, task, 1, [(0, 1), (1, 1)]),
        )))
        self.assertNotIn(followup, (v1_id, v2_id))
        self.assertEqual(get_accepted_piece(self.center, v1_id).piece.revision_id, v1_revision)
        self.assertEqual(get_accepted_interval_piece(self.center, v2_id).piece.revision_id, v2_revision)


class TestIntervalReview(IntervalCase):
    def test_public_examples(self):
        cases = json.loads(EXAMPLES.read_text(encoding='utf-8'))
        self.assertEqual(len(cases), 8)
        for case in cases:
            with self.subTest(case=case['case']):
                front_beats = tuple(row[0] for row in case['front'])
                back_beats = tuple(row[0] for row in case['back'])
                task = self.new_task(
                    front_beats, back_beats,
                    threshold=case['threshold'], limit=case['max_change'],
                )
                front, back = self.offline_interval_accept(task, case['front'], case['back'])
                report_id, receipt = issue_interval_review(self.center, task, front[2], back[2])
                self.assertEqual((receipt.report_id, receipt.task_id), (report_id, task))
                result = get_interval_review(self.center, report_id)
                self.assertEqual(result.reachable_counts, case['reachable_counts'])
                self.assertEqual((result.report_id, result.task_id), (report_id, task))
                self.assertEqual((result.front_id, result.back_id), (front[2], back[2]))
                self.assertEqual(result.front_source, (WEST, front[1], front[0]))
                self.assertEqual(result.back_source, (EAST, back[1], back[0]))
                self.assertEqual(result.receipt, receipt)

    def test_selection_errors(self):
        task = self.new_task((0,), (1,))
        other = self.new_task((0,), (1,), name='Bend')
        front, back = self.offline_interval_accept(task, [(0, 0, 0, 1)], [(1, 1, 1, 1)])
        other_front, other_back = self.offline_interval_accept(other, [(0, 0, 0, 1)], [(1, 1, 1, 1)])
        report_id, _ = issue_interval_review(self.center, task, front[2], back[2])
        self.assertEqual(get_interval_review(self.center, report_id).reachable_counts, [0, 1])
        v1_front = self.send(self.left, record_segment(self.left, task, 1, [(0, 0)]))
        for first, second in (
            (front[2], front[2]), (back[2], front[2]), (front[2], other_back[2]),
            (v1_front, back[2]), (front[2], v1_front),
        ):
            with self.subTest(first=first, second=second):
                with self.assertRaises(ValueError):
                    issue_interval_review(self.center, task, first, second)
                self.assertEqual(self.interval_review_counts(), (1, 1))
        with self.assertRaises(KeyError):
            issue_interval_review(self.center, task, front[2], back[2] + 100)
        with self.assertRaises(KeyError):
            issue_interval_review(self.center, task + 100, front[2], back[2])
        self.assertEqual(self.interval_review_counts(), (1, 1))

    def test_commit_failure_can_retry(self):
        task = self.new_task((0,), (1,))
        front, back = self.offline_interval_accept(task, [(0, 0, 0, 1)], [(1, 1, 1, 1)])
        ids = (front[2], back[2])
        self.assertEqual(self.interval_review_counts(), (0, 0))
        observer = self.open_db('center')

        def observe_pending_writes():
            self.assertTrue(self.center.in_transaction)
            self.assertEqual(self.interval_review_counts(), (1, 1))
            self.assertEqual(self.interval_review_counts(observer), (0, 0))

        fail_once = FailBeforeCommit(observe_pending_writes)
        with self.assertRaises(sqlite3.OperationalError) as caught:
            issue_interval_review(self.center, task, *ids, before_commit=fail_once)
        self.assertIs(caught.exception, fail_once.error)
        self.assertEqual(fail_once.calls, 1)
        self.assertFalse(self.center.in_transaction)
        self.assertEqual(self.interval_review_counts(), (0, 0))
        observer.close()
        report_id, receipt = issue_interval_review(self.center, task, *ids, before_commit=fail_once)
        self.assertEqual(fail_once.calls, 2)
        result = get_interval_review(self.center, report_id)
        self.assertEqual((result.front_id, result.back_id), ids)
        self.assertEqual(result.reachable_counts, [0, 1])
        self.assertEqual(result.receipt, receipt)
        self.assertEqual(self.interval_review_counts(), (1, 1))

    def test_empty_counts_issued(self):
        cases = json.loads(EXAMPLES.read_text(encoding='utf-8'))
        case = next(item for item in cases if item['case'] == 'local_empty')
        task = self.new_task((0, 1), (2,), threshold=case['threshold'], limit=case['max_change'])
        front, back = self.offline_interval_accept(task, case['front'], case['back'])
        report_id, receipt = issue_interval_review(self.center, task, front[2], back[2])
        result = get_interval_review(self.center, report_id)
        self.assertEqual(result.reachable_counts, [])
        self.assertEqual((receipt.report_id, receipt.task_id), (report_id, task))


class TestIntervalHistory(IntervalCase):
    def test_correction_and_reopen(self):
        task = self.new_task((0,), (1,))
        front_revision, front_piece, front_wire = self.interval_wire(
            self.left, task, 1, [(0, 0, 0, 1)],
        )
        back_revision, back_piece, back_wire = self.interval_wire(
            self.right, task, 2, [(1, 1, 1, 1)],
        )
        self.left.close()
        self.right.close()
        front_id = accept_interval_segment(self.center, front_wire)
        back_id = accept_interval_segment(self.center, back_wire)
        old_id, old_receipt = issue_interval_review(self.center, task, front_id, back_id)

        station = self.open_db(WEST)
        corrected = record_segment(station, task, 1, [(0, 1)], parent_id=front_revision)
        corrected_piece = freeze_interval_segment(station, corrected, [(0, 1, 1)])
        corrected_wire = export_interval_segment(station, corrected_piece)
        station.close()
        corrected_id = accept_interval_segment(self.center, corrected_wire)
        new_id, new_receipt = issue_interval_review(self.center, task, corrected_id, back_id)
        self.assertNotEqual(old_id, new_id)
        self.assertNotEqual(front_id, corrected_id)
        self.center.close()
        self.center = self.open_db('center')

        for number, receipt, front, source, counts in (
            (old_id, old_receipt, front_id, (WEST, front_piece, front_revision), [0, 1]),
            (new_id, new_receipt, corrected_id, (WEST, corrected_piece, corrected), [0]),
        ):
            with self.subTest(report_id=number):
                result = get_interval_review(self.center, number)
                self.assertEqual((result.report_id, result.task_id), (number, task))
                self.assertEqual((result.front_id, result.back_id), (front, back_id))
                self.assertEqual(result.front_source, source)
                self.assertEqual(result.back_source, (EAST, back_piece, back_revision))
                self.assertEqual(result.reachable_counts, counts)
                self.assertEqual(result.receipt, receipt)
                self.assertEqual((receipt.report_id, receipt.task_id), (number, task))
        with self.assertRaises(KeyError):
            get_interval_review(self.center, new_id + 100)
        self.assertEqual(
            get_accepted_interval_piece(self.center, front_id).piece.revision_id, front_revision,
        )
        self.assertEqual(
            get_accepted_interval_piece(self.center, corrected_id).piece.revision_id, corrected,
        )
        for _ in range(2):
            self.init_center(self.center)
        self.assertEqual(get_interval_review(self.center, old_id).reachable_counts, [0, 1])
        self.assertEqual(self.interval_review_counts(), (2, 2))


def brute_counts(spans, threshold, max_change, candidates):
    per_beat = [[v for v in candidates if lo <= v <= hi] for lo, hi in spans]
    totals = set()
    for combo in itertools.product(*per_beat):
        if all(abs(a - b) <= max_change for a, b in pairwise(combo)):
            totals.add(sum(1 for a, b in pairwise(combo) if a < threshold <= b))
    return sorted(totals)


class TestIntervalRandomized(IntervalCase):
    def test_against_brute_force(self):
        rng = random.Random(20261119)
        halves = [Fraction(n, 2) for n in range(-2, 5)]
        quarters = [Fraction(n, 4) for n in range(-4, 13)]
        nonnegative = [value for value in halves if value >= 0]
        widths = (Fraction(0), Fraction(1, 2), Fraction(1))
        for iteration in range(80):
            with self.subTest(iteration=iteration):
                threshold = rng.choice(halves)
                max_change = rng.choice(nonnegative)
                front_len = rng.randint(1, 3)
                back_len = rng.randint(1, 3)
                front_spans = []
                back_spans = []
                for spans, length in ((front_spans, front_len), (back_spans, back_len)):
                    for _ in range(length):
                        lo = rng.choice(halves)
                        spans.append((lo, lo + rng.choice(widths)))
                front_rows = [(i, lo, lo, hi) for i, (lo, hi) in enumerate(front_spans)]
                back_rows = [
                    (front_len + i, lo, lo, hi) for i, (lo, hi) in enumerate(back_spans)
                ]
                task = self.new_task(
                    tuple(range(front_len)),
                    tuple(range(front_len, front_len + back_len)),
                    threshold=threshold, limit=max_change,
                )
                front, back = self.offline_interval_accept(task, front_rows, back_rows)
                report_id, _ = issue_interval_review(self.center, task, front[2], back[2])
                result = get_interval_review(self.center, report_id)
                expected = brute_counts(
                    front_spans + back_spans, threshold, max_change, quarters,
                )
                self.assertEqual(result.reachable_counts, expected)
