from datetime import datetime

from openpyxl import load_workbook

from justvedio import daily, totals
from justvedio.batch import PersonResult, build_records
from justvedio.models import Candidate
from justvedio.records import write_daily_outcomes, write_outcomes

A = Candidate(2, '黔江区', '日更甲', '110101199001010011')
B = Candidate(3, '黔江区', '日更乙', '110101199001010022')


def records_of(**statuses):
    people = {'a': A, 'b': B}
    return {key: PersonResult(0, people[key], status=status) for key, status in statuses.items()}


def test_daily_ledger_keeps_one_entry_and_completed_wins(tmp_path):
    daily.record_person(records_of(a='failed')['a'], '2026-01-02', base=tmp_path)
    daily.record_person(records_of(b='failed')['b'], '2026-01-02', base=tmp_path)
    daily.record_person(records_of(a='completed')['a'], '2026-01-02', base=tmp_path)
    ledger = daily.load_day('2026-01-02', base=tmp_path)
    assert len(ledger) == 2
    assert ledger[A.id_number]['status'] == 'completed'
    assert ledger[B.id_number]['status'] == 'failed'


def test_daily_ledger_seeds_from_same_day_workbooks(tmp_path):
    write_outcomes([
        PersonResult(0, A, status='completed'),
        PersonResult(1, B, status='failed', reason='未找到入口'),
    ], datetime(2026, 1, 2, 3, 4, 5), base=tmp_path)
    ledger = daily.load_day('2026-01-02', base=tmp_path)
    assert ledger[A.id_number]['status'] == 'completed'
    assert ledger[B.id_number]['status'] == 'failed'
    daily.record_person(records_of(b='completed')['b'], '2026-01-02', base=tmp_path)
    ledger = daily.load_day('2026-01-02', base=tmp_path)
    assert len(ledger) == 2 and ledger[B.id_number]['status'] == 'completed'


def test_roster_drops_duplicate_rejected_rows_and_skips_completed(tmp_path):
    prior = {
        A.id_number: {'status': 'completed', 'source': 'learned', 'reason': '', 'updated': ''},
        B.id_number: {'status': 'failed', 'source': 'learned', 'reason': '未完成', 'updated': ''},
    }
    rejected = [(Candidate(4, '黔江区', '重复甲', A.id_number), '身份重复'),
                (Candidate(5, '黔江区', '重复乙', B.id_number), '身份重复')]
    records = build_records([A, B], rejected, prior, retry_incomplete=False)
    assert [(record.candidate.id_number, record.status) for record in records] == [
        (A.id_number, 'completed'), (B.id_number, 'failed')]
    retry = build_records([A, B], rejected, prior, retry_incomplete=True)
    assert [(record.candidate.id_number, record.status) for record in retry] == [
        (A.id_number, 'completed'), (B.id_number, 'pending')]


def test_daily_workbook_merges_and_completed_wins(tmp_path):
    write_daily_outcomes([
        PersonResult(0, A, status='completed'),
        PersonResult(1, B, status='failed', reason='第一次失败'),
    ], datetime(2026, 1, 2, 3, 4, 5), base=tmp_path)
    write_daily_outcomes([
        PersonResult(0, A, status='failed', reason='重试前'),
        PersonResult(1, B, status='completed'),
    ], datetime(2026, 1, 2, 9, 0, 0), base=tmp_path)
    completed = tmp_path/'学习完成'/'学习完成_20260102.xlsx'
    failed = tmp_path/'学习失败'/'学习失败_20260102.xlsx'
    book = load_workbook(completed, read_only=True)
    try:
        rows = list(book.active.values)
    finally:
        book.close()
    assert [row[2] for row in rows[1:]] == [A.id_number, B.id_number]
    book = load_workbook(failed, read_only=True)
    try:
        assert book.active.max_row == 1
    finally:
        book.close()


def test_cumulative_seed_deduplicates_overlapping_daily_batches(tmp_path):
    write_outcomes([PersonResult(0, A, status='completed'),
                    PersonResult(1, B, status='completed')],
                   datetime(2026, 1, 2, 3, 4, 5), base=tmp_path)
    write_outcomes([PersonResult(0, A, status='completed')],
                   datetime(2026, 1, 2, 9, 0, 0), base=tmp_path)
    assert totals.load_completed_learning(base=tmp_path) == 2
