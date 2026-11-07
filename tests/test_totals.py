import json
from datetime import datetime

from justvedio import paths, totals
from justvedio.batch import PersonResult
from justvedio.models import Candidate
from justvedio.records import write_outcomes


PEOPLE = [
    Candidate(2, '黔江区', '累计甲', '110101199001010011'),
    Candidate(3, '黔江区', '累计乙', '110101199001010022'),
]


def test_missing_counter_starts_at_zero():
    assert totals.load_completed_learning() == 0
    assert paths.lifetime_stats_file().is_file()


def test_every_completion_is_added_and_persisted():
    assert totals.record_completed_learning() == 1
    assert totals.record_completed_learning() == 2
    assert totals.load_completed_learning() == 2
    payload = json.loads(paths.lifetime_stats_file().read_text(encoding='utf-8'))
    assert payload['completed_learning'] == 2


def test_first_read_seeds_from_existing_completed_workbooks():
    write_outcomes([
        PersonResult(0, PEOPLE[0], status='completed'),
        PersonResult(1, PEOPLE[1], status='completed'),
        PersonResult(2, PEOPLE[1], status='failed', reason='失败不计入'),
    ], datetime(2026, 1, 2, 3, 4, 5))
    assert totals.load_completed_learning() == 2
    assert totals.record_completed_learning() == 3


def test_corrupt_counter_is_rebuilt_from_saved_records():
    write_outcomes([PersonResult(0, PEOPLE[0], status='completed')], datetime(2026, 1, 2, 3, 4, 5))
    paths.lifetime_stats_file().parent.mkdir(parents=True, exist_ok=True)
    paths.lifetime_stats_file().write_text('{not json', encoding='utf-8')
    assert totals.load_completed_learning() == 1
    assert totals.record_completed_learning() == 2


def test_same_person_learning_again_still_adds_one():
    write_outcomes([PersonResult(0, PEOPLE[0], status='completed')], datetime(2026, 1, 2, 3, 4, 5))
    assert totals.load_completed_learning() == 1
    assert totals.record_completed_learning() == 2
    assert totals.record_completed_learning() == 3
    assert totals.load_completed_learning() == 3
