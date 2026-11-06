from datetime import datetime
from openpyxl import load_workbook
from justvedio.batch import PersonResult
from justvedio.models import Candidate
from justvedio.records import write_outcomes
from justvedio import paths

PEOPLE = [
    Candidate(2, '黔江区', '记录甲', '110101199001010011'),
    Candidate(3, '黔江区', '记录乙', '110101199001010022'),
    Candidate(4, '黔江区', '记录丙', '110101199001010033'),
]


def test_outcome_files_follow_import_template_and_batch_time():
    records = [
        PersonResult(0, PEOPLE[0], status='completed'),
        PersonResult(1, PEOPLE[1], status='failed', reason='未找到旁听学习入口'),
        PersonResult(2, PEOPLE[2], status='pending'),
    ]
    targets = write_outcomes(records, datetime(2026, 1, 2, 3, 4, 5))
    assert targets['completed'].name == '学习完成_20260102_030405.xlsx'
    assert targets['failed'].name == '学习失败_20260102_030405.xlsx'
    assert targets['completed'].parent == paths.completed_folder()
    assert targets['failed'].parent == paths.failed_folder()
    book = load_workbook(targets['completed'], read_only=True)
    try:
        rows = list(book.active.values)
        assert rows == [('所在的区县', '姓名', '身份证号'), ('黔江区', '记录甲', '110101199001010011')]
    finally:
        book.close()
    book = load_workbook(targets['failed'], read_only=True)
    try:
        rows = list(book.active.values)
        assert rows[0] == ('所在的区县', '姓名', '身份证号')
        assert [row[2] for row in rows[1:]] == ['110101199001010022']
    finally:
        book.close()


def test_second_batch_in_the_same_second_does_not_overwrite():
    records = [PersonResult(0, PEOPLE[0], status='completed')]
    first = write_outcomes(records, datetime(2026, 1, 2, 3, 4, 5))
    second = write_outcomes(records, datetime(2026, 1, 2, 3, 4, 5))
    assert first['completed'] != second['completed']
    assert second['completed'].name == '学习完成_20260102_030405_2.xlsx'


def test_ensure_folders_creates_data_directories(tmp_path):
    base = tmp_path / 'exe'
    folders = paths.ensure_folders(base)
    assert [folder.name for folder in folders] == ['人员信息', '学习完成', '学习失败']
    assert all(folder.is_dir() for folder in folders)
    assert (paths.identities_folder(base) / '说明.txt').is_file()
