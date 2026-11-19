from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from database import connect
from intake.registry import (
    accept_interval_segment, accept_segment, get_accepted_piece, initialize_intake,
)
from ledger.ingest import record_segment
from ledger.query import get_revision
from ledger.storage import initialize_ledger
from plan.catalog import get_task, initialize_catalog, install_task_snapshot
from plan.layout import SegmentLayout
from plan.rationals import rational_text
from plan.tasks import open_task
from review.history import get_interval_review, get_review
from review.issue import issue_interval_review, issue_review
from review.storage import initialize_review
from station.export import export_interval_segment, export_segment
from station.freeze import freeze_interval_segment, freeze_segment
from station.storage import initialize_station


SAMPLE = Path(__file__).resolve().parent / 'examples' / 'day_shift.json'
INTERVAL_SAMPLE = Path(__file__).resolve().parent / 'examples' / 'interval_shift.json'


def checked(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, got {actual!r}')


def receive_station(root, snapshot, slot, part, *, parent_id=None):
    with closing(connect(root / f'station-{slot}.sqlite')) as db:
        initialize_catalog(db)
        initialize_ledger(db, part['origin'])
        initialize_station(db)
        install_task_snapshot(db, snapshot)
        values = part['values'] if parent_id is None else part['corrected_values']
        samples = zip(part['beats'], values, strict=True)
        revision = record_segment(db, snapshot.task_id, slot, samples, parent_id=parent_id)
        if parent_id is not None:
            checked(get_revision(db, revision).parent_id, parent_id)
            checked([str(value) for _, value in get_revision(db, parent_id).samples],
                    [str(value) for value in part['values']])
        return revision, export_segment(db, freeze_segment(db, revision))


def counts(result):
    seam = result.seam
    return {
        'front_crossings': result.front_crossings,
        'back_crossings': result.back_crossings,
        'seam_values': [rational_text(seam.before), rational_text(seam.after)],
        'seam_change': rational_text(seam.change),
        'seam_crossings': seam.crossings,
        'total_crossings': result.total_crossings,
    }


def provenance(center, result):
    parents = [get_accepted_piece(center, number) for number in (result.front_id, result.back_id)]
    return {
        'report_id': result.report_id,
        'task_id': result.task_id,
        'acceptances': [parent.acceptance_id for parent in parents],
        'revisions': [parent.piece.revision_id for parent in parents],
        'receipt': [result.receipt.report_id, result.receipt.task_id],
    }


def emit(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    checked(actual, expected)
    checked(downstream_actual, downstream_expected)
    event = {
        'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': paths, 'oracle': oracle,
    }
    print('POINTWISE_SCENARIO ' + json.dumps(event, ensure_ascii=False, separators=(',', ':')))


def run(root, data):
    front, back = data['front'], data['back']
    segments = tuple(
        SegmentLayout(slot, part['origin'], part['rig'], tuple(part['beats']))
        for slot, part in enumerate((front, back), start=1)
    )
    old_expected = {
        'front_crossings': 0, 'back_crossings': 0, 'seam_values': ['0/1', '1/1'],
        'seam_change': '1/1', 'seam_crossings': 1, 'total_crossings': 1,
    }
    new_expected = {
        'front_crossings': 0, 'back_crossings': 0, 'seam_values': ['0/1', '0/1'],
        'seam_change': '0/1', 'seam_crossings': 0, 'total_crossings': 0,
    }
    center_path = root / 'center.sqlite'
    with closing(connect(center_path)) as center:
        initialize_catalog(center)
        initialize_intake(center)
        initialize_review(center)
        task_id = open_task(center, data['protocol'], data['unit'], data['threshold'], data['max_change'], segments)
        snapshot = get_task(center, task_id)
        first_revision, first_wire = receive_station(root, snapshot, 1, front)
        original_revision, original_wire = receive_station(root, snapshot, 2, back)
        front_id = accept_segment(center, first_wire)
        original_id = accept_segment(center, original_wire)
        report, receipt = issue_review(center, task_id, front_id, original_id)
        checked((receipt.report_id, receipt.task_id), (report, task_id))
        original = get_review(center, report)
        first_provenance = {
            'report_id': report, 'task_id': task_id, 'acceptances': [front_id, original_id],
            'revisions': [first_revision, original_revision], 'receipt': [report, task_id],
        }
        emit(
            'seam_count',
            {'threshold': data['threshold'], 'max_change': data['max_change'],
             'front': front['values'], 'back': back['values'], 'stations_closed': True},
            old_expected, counts(original), first_provenance, provenance(center, original),
            ['station/freeze.py', 'intake/registry.py', 'review/join.py', 'review/history.py'],
            '手算相邻对 0→0、0→1、1→1，只有接缝达到门槛。原选件以接纳返回的编号核对。',
        )

        corrected_revision, corrected_wire = receive_station(root, snapshot, 2, back, parent_id=original_revision)
        corrected_id = accept_segment(center, corrected_wire)
        new_report, new_receipt = issue_review(center, task_id, front_id, corrected_id)
        checked((new_receipt.report_id, new_receipt.task_id), (new_report, task_id))
        if report == new_report or original_id == corrected_id:
            raise AssertionError('corrected revision and report require distinct identities')
        second_provenance = {
            'report_id': new_report, 'task_id': task_id, 'acceptances': [front_id, corrected_id],
            'revisions': [first_revision, corrected_revision], 'receipt': [new_report, task_id],
        }

    with closing(connect(center_path)) as reopened:
        old_result = get_review(reopened, report)
        new_result = get_review(reopened, new_report)
        emit(
            'historical',
            {'old_report': report, 'new_report': new_report, 'corrected_back': back['corrected_values']},
            {'old': old_expected, 'new': new_expected},
            {'old': counts(old_result), 'new': counts(new_result)},
            {'old': first_provenance, 'new': second_provenance},
            {'old': provenance(reopened, old_result), 'new': provenance(reopened, new_result)},
            ['ledger/revisions.py', 'station/freeze.py', 'review/issue.py', 'review/storage.py', 'review/history.py'],
            '旧读数一次，勘误后四拍均为零。重开的领取结果按两次签发前选定的接纳号和修订号核对。',
        )


def interval_counts(result):
    return {'reachable_counts': list(result.reachable_counts)}


def interval_provenance(result):
    return {
        'report_id': result.report_id,
        'task_id': result.task_id,
        'acceptances': [result.front_id, result.back_id],
        'revisions': [result.front_source.revision_id, result.back_source.revision_id],
        'receipt': [result.receipt.report_id, result.receipt.task_id],
    }


def receive_interval_station(path, origin, snapshot, slot, rows, *, parent_id=None):
    with closing(connect(path)) as db:
        initialize_catalog(db)
        initialize_ledger(db, origin)
        initialize_station(db)
        install_task_snapshot(db, snapshot)
        samples = [(row[0], row[1]) for row in rows]
        revision = record_segment(db, snapshot.task_id, slot, samples, parent_id=parent_id)
        spans = [(row[0], row[2], row[3]) for row in rows]
        piece = freeze_interval_segment(db, revision, spans)
        return revision, export_interval_segment(db, piece)


def run_intervals(root):
    cases = json.loads(INTERVAL_SAMPLE.read_text(encoding='utf-8'))
    case = next(item for item in cases if item['case'] == 'two_counts')
    front_rows = [tuple(row) for row in case['front']]
    back_rows = [tuple(row) for row in case['back']]
    segments = (
        SegmentLayout(1, 'west', 'W1', tuple(row[0] for row in front_rows)),
        SegmentLayout(2, 'east', 'E1', tuple(row[0] for row in back_rows)),
    )
    west_path = root / 'interval-west.sqlite'
    east_path = root / 'interval-east.sqlite'
    center_path = root / 'interval-center.sqlite'
    with closing(connect(center_path)) as center:
        initialize_catalog(center)
        initialize_intake(center)
        initialize_review(center)
        task_id = open_task(
            center, f"榆湾夜班区间复核 {case['case']}", 'kN',
            case['threshold'], case['max_change'], segments,
        )
        snapshot = get_task(center, task_id)
        front_revision, front_wire = receive_interval_station(west_path, 'west', snapshot, 1, front_rows)
        back_revision, back_wire = receive_interval_station(east_path, 'east', snapshot, 2, back_rows)
        front_id = accept_interval_segment(center, front_wire)
        back_id = accept_interval_segment(center, back_wire)
        report, receipt = issue_interval_review(center, task_id, front_id, back_id)
        checked((receipt.report_id, receipt.task_id), (report, task_id))
        original = get_interval_review(center, report)
        checked(original.reachable_counts, case['reachable_counts'])
        original_provenance = interval_provenance(original)
        emit(
            'interval_offline',
            {'case': case['case'], 'threshold': case['threshold'], 'max_change': case['max_change'],
             'front': case['front'], 'back': case['back'], 'stations_closed': True},
            {'reachable_counts': case['reachable_counts']}, interval_counts(original),
            original_provenance, interval_provenance(original),
            ['station/intervals.py', 'station/freeze.py', 'intake/registry.py',
             'review/interval_join.py', 'review/history.py'],
            '两站关闭后中心只凭 V2 证据核定：前段末拍 [0,1] 与后段首拍 [1,1] 的接缝可计 0 或 1 次，整程可达 [0,1]。',
        )

        corrected_revision, corrected_wire = receive_interval_station(
            west_path, 'west', snapshot, 1, [(0, 1, 1, 1)], parent_id=front_revision,
        )
        corrected_id = accept_interval_segment(center, corrected_wire)
        new_report, new_receipt = issue_interval_review(center, task_id, corrected_id, back_id)
        checked((new_receipt.report_id, new_receipt.task_id), (new_report, task_id))
        corrected = get_interval_review(center, new_report)
        checked(corrected.reachable_counts, [0])
        if report == new_report or front_id == corrected_id:
            raise AssertionError('corrected interval revision requires distinct identities')
        corrected_provenance = interval_provenance(corrected)

    with closing(connect(center_path)) as reopened:
        old = get_interval_review(reopened, report)
        new = get_interval_review(reopened, new_report)
        checked(old.reachable_counts, case['reachable_counts'])
        checked((old.front_id, old.back_id), (front_id, back_id))
        checked((old.front_source.revision_id, old.back_source.revision_id),
                (front_revision, back_revision))
        checked(new.reachable_counts, [0])
        checked(new.front_source.revision_id, corrected_revision)
        emit(
            'interval_correction',
            {'old_report': report, 'new_report': new_report, 'corrected_front': [[0, 1, 1, 1]]},
            {'old': {'reachable_counts': case['reachable_counts']}, 'new': {'reachable_counts': [0]}},
            {'old': interval_counts(old), 'new': interval_counts(new)},
            {'old': original_provenance, 'new': corrected_provenance},
            {'old': interval_provenance(old), 'new': interval_provenance(new)},
            ['ledger/ingest.py', 'station/freeze.py', 'review/issue.py',
             'review/storage.py', 'review/history.py'],
            '前站另记修订并把区间固定为 1 后另签 [0]；重开中心按原号领取旧报告 [0,1] 及其原选件。',
        )


def main():
    data = json.loads(SAMPLE.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='yuwan-demo-') as folder:
        root = Path(folder)
        run(root, data)
        run_intervals(root)


if __name__ == '__main__':
    main()
