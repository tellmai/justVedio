import asyncio
import time
from datetime import datetime
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from justvedio.controller import BrowserWorker
from justvedio.browsers import BrowserChoice
from justvedio.models import Candidate, SiteConfig, VideoOptions
from test_integration import wait


def setup_worker(monkeypatch):
    from justvedio.browsers import launch_process as real_launch
    launched = []
    async def launch(playwright, choice, headless=False, progress=lambda _: None):
        running = await real_launch(playwright, choice, True, progress)
        launched.append(running)
        return running
    monkeypatch.setattr('justvedio.controller.launch_process', launch)
    app = QApplication.instance() or QApplication([])
    worker = BrowserWorker()
    async def recognize(_):
        return 'TEST'
    monkeypatch.setattr(worker.ocr, 'recognize', recognize)
    ready, finished, errors = [], [], []
    worker.ready.connect(lambda: ready.append(True))
    worker.job_finished.connect(lambda: finished.append(True))
    worker.failed.connect(errors.append)
    worker.start()
    wait(app, lambda: ready)
    return app, worker, finished, errors, launched


def launch(worker, origin, chrome, output, count=3, lanes=1, timeout=60):
    people = [Candidate(i+2, '黔江区', f'合成人员{i}', f'11010119900101{i:04}') for i in range(count)]
    options = VideoOptions(background=True, video_timeout_seconds=timeout, post_completion_wait_seconds=0)
    browsers = [BrowserChoice(f'测试浏览器{i+1}', chrome, i) for i in range(lanes)]
    worker.start_job('watch', SiteConfig(origin+'/exam/', chrome, 10000, True), people, str(output),
                     options=options, browsers=browsers, outcome_root=str(output/'records'),
                     started_at=datetime(2026, 1, 2, 3, 4, 5))
    return people


def test_learning_completes_and_closes_each_browser(local_site, chrome, tmp_path, monkeypatch):
    origin, state = local_site
    app, worker, finished, errors, launched = setup_worker(monkeypatch)
    try:
        launch(worker, origin, chrome, tmp_path, count=5, lanes=2)
        wait(app, lambda: finished, 120)
        records = worker.last_store.records
        assert not errors and all(r.status == 'completed' for r in records), [(r.status, r.reason) for r in records]
        assert all(r.browser in {'测试浏览器1', '测试浏览器2'} for r in records)
        assert {r.browser for r in records} == {'测试浏览器1', '测试浏览器2'}
        assert len(launched) == 5 and all(item.process.poll() is not None for item in launched)
        assert len(state['learning_visits']) == 5 and state['confirmations'] == 5
        assert not worker.active_browsers and not worker.active_pages
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


def test_chrome_and_edge_learning_concurrently(local_site, tmp_path, monkeypatch):
    from justvedio.browsers import discover_browsers
    found = {choice.name: choice for choice in discover_browsers()}
    chrome_choice = found.get('Google Chrome')
    edge_choice = found.get('Microsoft Edge')
    if chrome_choice is None or edge_choice is None:
        pytest.skip('需要同时安装 Google Chrome 与 Microsoft Edge')
    origin, state = local_site
    app, worker, finished, errors, launched = setup_worker(monkeypatch)
    people = [Candidate(i+2, '黔江区', f'双浏览器{i}', f'11010119900101{i:04}') for i in range(4)]
    try:
        options = VideoOptions(background=True, video_timeout_seconds=60, post_completion_wait_seconds=0)
        worker.start_job('watch', SiteConfig(origin+'/exam/', chrome_choice.path, 10000, True),
                         people, str(tmp_path), options=options,
                         browsers=[chrome_choice, edge_choice],
                         outcome_root=str(tmp_path/'records'), started_at=datetime(2026, 1, 2, 3, 4, 5))
        wait(app, lambda: finished, 180)
        records = worker.last_store.records
        assert not errors and all(record.status == 'completed' for record in records), [(r.status, r.reason) for r in records]
        assert {record.browser for record in records} == {'Google Chrome', 'Microsoft Edge'}
        assert len(launched) == 4 and all(item.process.poll() is not None for item in launched)
        assert state['confirmations'] == 4
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


def test_edge_browser_learning_flow(local_site, tmp_path, monkeypatch):
    from justvedio.browsers import discover_browsers
    edge = next((choice for choice in discover_browsers() if 'Edge' in choice.name), None)
    if edge is None:
        pytest.skip('未安装 Microsoft Edge')
    origin, state = local_site
    app, worker, finished, errors, launched = setup_worker(monkeypatch)
    try:
        launch(worker, origin, edge.path, tmp_path, count=1, lanes=1)
        wait(app, lambda: finished, 120)
        assert not errors and worker.last_store.records[0].status == 'completed'
        assert state['confirmations'] == 1
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


def test_click_starts_video_before_media_preload(local_site, chrome, tmp_path, monkeypatch):
    origin, state = local_site
    app, worker, finished, errors, launched = setup_worker(monkeypatch)
    person = Candidate(2, '黔江区', '延迟加载', '110101199001010099')
    state['slow_ready'].add(person.id_number)
    try:
        options = VideoOptions(background=True, video_timeout_seconds=30, post_completion_wait_seconds=0)
        worker.start_job('watch', SiteConfig(origin+'/exam/', chrome, 10000, True), [person],
                         str(tmp_path), options=options,
                         browsers=[BrowserChoice('测试浏览器1', chrome, 0)],
                         outcome_root=str(tmp_path/'records'), started_at=datetime(2026, 1, 2, 3, 4, 5))
        wait(app, lambda: finished, 120)
        assert not errors and worker.last_store.records[0].status == 'completed'
        assert state['confirmations'] == 1 and state['finished_visits'] == 1
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


def test_enter_exam_only_has_actionable_failure_reason(local_site, chrome, tmp_path, monkeypatch):
    origin, state = local_site
    state['exam_only'].add('110101199001010000')
    app, worker, finished, errors, launched = setup_worker(monkeypatch)
    try:
        launch(worker, origin, chrome, tmp_path, count=1, lanes=1)
        wait(app, lambda: finished, 120)
        record = worker.last_store.records[0]
        assert not errors and record.status == 'failed'
        assert '发现进入考试按钮，请先完成考试' in record.reason
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


def test_missing_learning_entry_marks_failed_and_continues(local_site, chrome, tmp_path, monkeypatch):
    origin, state = local_site
    app, worker, finished, errors, launched = setup_worker(monkeypatch)
    try:
        people = launch(worker, origin, chrome, tmp_path, count=3, lanes=1)
        state['no_learning_entry'].add(people[0].id_number)
        wait(app, lambda: finished, 120)
        records = worker.last_store.records
        assert not errors
        assert records[0].status == 'failed' and '旁听学习' in records[0].reason
        assert all(r.status == 'completed' for r in records[1:])
        assert len(launched) == 3 and all(item.process.poll() is not None for item in launched)
        assert len(state['learning_visits']) == 2
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


@pytest.mark.parametrize('immediate', [False, True])
def test_stop_during_learning_leaves_the_rest_pending(local_site, chrome, tmp_path, monkeypatch, immediate):
    origin, _ = local_site
    app, worker, finished, errors, launched = setup_worker(monkeypatch)
    try:
        launch(worker, origin, chrome, tmp_path, count=3, lanes=1)
        wait(app, lambda: worker.last_store and worker.last_store.records[0].status == 'watching')
        worker.stop_job() if immediate else worker.stop_after_current()
        wait(app, lambda: finished, 120)
        assert [r.status for r in worker.last_store.records] == [('stopped' if immediate else 'completed'), 'pending', 'pending']
        assert all(item.process.poll() is None for item in launched)
        assert not worker.active_browsers
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())
        from justvedio.browsers import terminate_process_tree
        for item in launched:
            terminate_process_tree(item.process)
            item._cleanup_files()


def test_outcome_files_split_completed_and_failed(local_site, chrome, tmp_path, monkeypatch):
    from openpyxl import load_workbook
    origin, state = local_site
    app, worker, finished, errors, launched = setup_worker(monkeypatch)
    try:
        people = launch(worker, origin, chrome, tmp_path, count=3, lanes=1)
        state['no_learning_entry'].add(people[1].id_number)
        wait(app, lambda: finished, 120)
        completed = list((tmp_path/'records'/'学习完成').glob('学习完成_20260102*.xlsx'))
        failed = list((tmp_path/'records'/'学习失败').glob('学习失败_20260102*.xlsx'))
        assert len(completed) == 1 and len(failed) == 1
        assert completed[0].name == '学习完成_20260102.xlsx'
        book = load_workbook(completed[0], read_only=True)
        try:
            rows = list(book.active.values)
            assert len(rows) == 3 and rows[0] == ('所在的区县', '姓名', '身份证号')
            assert [row[2] for row in rows[1:]] == [people[0].id_number, people[2].id_number]
        finally:
            book.close()
        book = load_workbook(failed[0], read_only=True)
        try:
            rows = list(book.active.values)
            assert len(rows) == 2 and rows[1][2] == people[1].id_number
        finally:
            book.close()
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


def test_application_exit_keeps_running_browsers(monkeypatch):
    class FakeRunning:
        def __init__(self):
            self.closed = False
        def is_open(self):
            return not self.closed
        async def close(self):
            self.closed = True
            return True
    worker = BrowserWorker()
    try:
        kept = FakeRunning()
        worker.active_browsers[0] = kept
        worker._preserve = True
        asyncio.run(worker._cleanup())
        assert not kept.closed and not worker.active_browsers
        worker._preserve = False
        closed = FakeRunning()
        worker.active_browsers[0] = closed
        asyncio.run(worker._cleanup())
        assert closed.closed and not worker.active_browsers
    finally:
        worker.ocr.close()


def test_source_self_check_reports_learning_flow(tmp_path):
    from justvedio.selftest import run_runtime_checks
    result = run_runtime_checks(tmp_path)
    assert result['learning_flow'] and result['completed'] == 12
    assert result['browser_per_person'] and result['browser_closed_after_learning']
    assert result['outcome_files'] and result['outcome_format'] and result['browser_round_robin']
    assert result['learning_visits'] == 12 and result['confirmations'] == 12
    assert result['max_active'] <= 2
    assert result['lifetime_completed'] == 12


@pytest.mark.parametrize('concurrency,background', [(True, True), (0, True), (31, True), (1.5, True), (10, 'yes')])
def test_invalid_execution_options_are_rejected(concurrency, background):
    with pytest.raises(ValueError):
        VideoOptions(concurrency=concurrency, background=background).validate_execution()
