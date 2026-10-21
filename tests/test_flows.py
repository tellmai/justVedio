import asyncio
import pytest
from PySide6.QtWidgets import QApplication
from justvedio.controller import BrowserWorker
from justvedio.models import Candidate, SiteConfig, VideoOptions
from justvedio.selftest import run_runtime_checks
from test_integration import wait


def setup_worker(monkeypatch):
    from justvedio.browsers import launch_browser as real_launch
    async def launch(p, explicit='', headless=False, progress=lambda _: None):
        return await real_launch(p, explicit, True, progress)
    monkeypatch.setattr('justvedio.controller.launch_browser', launch)
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
    return app, worker, finished, errors


def launch(worker, origin, chrome, output, count=3, concurrency=1, entry=False):
    people = [Candidate(i+2, '黔江区', f'合成人员{i}', f'11010119900101{i:04}') for i in range(count)]
    options = VideoOptions(concurrency=concurrency, video_url='' if entry else origin+'/watch',
                           entry_selector='#video-link' if entry else '', play_selector='#play',
                           complete_selector='#completed', video_timeout_seconds=20, stall_timeout_seconds=5)
    worker.start_job('watch', SiteConfig(origin+'/exam/', chrome, 10000, True), people, str(output),
                     options=options, test_mode=True)
    return people


def test_twelve_real_logins_directly_watch_and_export(tmp_path):
    result = run_runtime_checks(tmp_path)
    assert result['completed'] == 12 and 1 < result['max_contexts'] <= 10
    assert all(result[key] for key in ('statistics_export', 'identity_isolation', 'direct_video_transition',
                                      'no_answering_fields', 'power_request_released'))


@pytest.mark.parametrize('phase', ['login', 'video'])
def test_failure_does_not_block_next(local_site, chrome, tmp_path, monkeypatch, phase):
    origin, state = local_site
    bad = '110101199001010000'
    state['bad_ids' if phase == 'login' else 'bad_video_ids'].add(bad)
    app, worker, finished, errors = setup_worker(monkeypatch)
    try:
        launch(worker, origin, chrome, tmp_path)
        wait(app, lambda: finished)
        records = worker.last_store.records
        assert not errors and records[0].status == 'failed'
        assert records[0].stage == ('登录验证' if phase == 'login' else '视频观看')
        assert all(r.status == 'completed' and r.videos_completed == 1 for r in records[1:])
        assert worker.browser is None and not worker.sessions and not worker.power_guard.active
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


@pytest.mark.parametrize('immediate', [False, True])
def test_stop_during_video_does_not_admit_next(local_site, chrome, tmp_path, monkeypatch, immediate):
    origin, _ = local_site
    app, worker, finished, errors = setup_worker(monkeypatch)
    try:
        launch(worker, origin, chrome, tmp_path)
        wait(app, lambda: worker.last_store and worker.last_store.records[0].status == 'watching')
        worker.stop_job() if immediate else worker.stop_after_current()
        wait(app, lambda: finished)
        assert not errors
        assert [r.status for r in worker.last_store.records] == [('stopped' if immediate else 'completed'), 'pending', 'pending']
        assert worker.browser is None and not worker.sessions and not worker.power_guard.active
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


def test_configurable_site_entry_retains_login_cookie(local_site, chrome, tmp_path, monkeypatch):
    origin, state = local_site
    app, worker, finished, errors = setup_worker(monkeypatch)
    try:
        people = launch(worker, origin, chrome, tmp_path, count=1, entry=True)
        wait(app, lambda: finished)
        assert not errors and worker.last_store.records[0].status == 'completed'
        assert state['watch_visits'] == [(people[0].id_number, 1)]
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())


@pytest.mark.parametrize('concurrency,background', [(True, True), (0, True), (31, True), (1.5, True), (10, 'yes')])
def test_invalid_execution_options_are_rejected(concurrency, background):
    with pytest.raises(ValueError):
        VideoOptions(concurrency=concurrency, background=background).validate_execution()
