"""Explicit source/portable checks; synthetic identities stay on loopback."""
import asyncio
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path


def wait_for(app, condition, seconds=90):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    if not condition():
        raise RuntimeError('离线流程等待超时')


def check_gui(window, app, output):
    from PySide6.QtWidgets import QPushButton, QLabel
    from .models import Candidate, IdentityImport
    from .version import APP_NAME
    from .expiry import is_expired, EXPIRES_AT
    people = [Candidate(i+2, '黔江区', f'离线人员{i}', f'11010119900101{i:04}') for i in range(12)]
    window.identities_loaded(IdentityImport(people, [], '合成身份'))
    window.background.setChecked(True)
    ready = window.start_button.isEnabled() and window.start_button.text() == '启动视频学习'
    app.processEvents()
    window.grab().save(str(output/'视频学习预览.png'))
    chosen = window._selected_browsers()
    texts = [w.text() for kind in (QPushButton, QLabel) for w in window.findChildren(kind)]
    return dict(brand_matches=window.windowTitle().startswith(APP_NAME), learning_button=ready,
                background_checkbox=window.background.text() == '后台执行（隐藏浏览器）',
                browser_list=bool(window.browser_choices), browser_selected=bool(chosen),
                selected_browser_names=[choice.name for choice in chosen],
                no_test_mode=not hasattr(window, 'test_mode'),
                no_tray=not hasattr(window, 'tray') and not hasattr(window, 'background_button'),
                no_answering_ui=not any(any(term in text for term in ('答题', '题库', '评分')) for text in texts),
                expiry_enforced=not is_expired(EXPIRES_AT-timedelta(microseconds=1)) and is_expired(EXPIRES_AT))


def run_runtime_checks(output, desktop=False, window=None):
    from openpyxl import Workbook, load_workbook
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from .models import Candidate, VideoOptions, SiteConfig
    from .importers import load_identities
    from .ocr import LocalOCR
    from .fixtures import SyntheticSite
    from .controller import BrowserWorker
    from .browsers import BrowserChoice, discover_browsers, launch_process as real_launch_process
    from . import controller
    app = QApplication.instance() or QApplication([])
    people = [Candidate(i+2, '黔江区', f'离线人员{i}', f'11010119900101{i:04}') for i in range(12)]
    wb = Workbook()
    wb.active.append(['所在的区县', '姓名', '身份证号'])
    for person in people:
        wb.active.append([person.district, person.name, person.id_number])
    identity_file = output/'selftest-identities.xlsx'
    wb.save(identity_file)
    wb.close()
    if load_identities(str(identity_file)).candidates != people:
        raise RuntimeError('身份导入自检失败')
    ocr = LocalOCR()
    try:
        asyncio.run(ocr.check())
    finally:
        ocr.close()
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    bundled = base/'chrome/chrome-win64/chrome.exe'
    if not bundled.is_file():
        bundled = base/'tools/chrome/chrome-win64/chrome.exe'
    media = base/'justvedio/assets/selftest.webm'
    if bundled.is_file():
        choices = [BrowserChoice(f'随附 Chrome {index+1}', str(bundled), 3) for index in range(2)]
    else:
        choices = discover_browsers()[:2]
    if not choices:
        raise RuntimeError('未发现可用于自检的浏览器')
    lane_count = len(choices)
    worker = window.backend if window is not None else BrowserWorker()
    ready, finished, errors, transitions, peaks = [], [], [], {}, []
    worker.ready.connect(lambda: ready.append(True))
    worker.job_finished.connect(lambda: finished.append(True))
    worker.failed.connect(errors.append)
    def changed(record):
        chain = transitions.setdefault(record.index, [])
        if not chain or chain[-1] != record.status:
            chain.append(record.status)
        peaks.append(len(worker.active_browsers))
    worker.person_updated.connect(changed)
    async def recognize(_):
        return 'TEST'
    original_recognize = worker.ocr.recognize
    worker.ocr.recognize = recognize
    original_launch = controller.launch_process
    launches, launch_modes, browser_pids = [], [], set()
    async def launch(playwright, choice, headless=False, progress=lambda _: None):
        launch_modes.append(headless)
        running = await real_launch_process(playwright, choice, headless, progress)
        launches.append(running)
        if desktop:
            cdp = await running.browser.new_browser_cdp_session()
            try:
                info = await cdp.send('SystemInfo.getProcessInfo')
                browser_pids.add(next(int(item['id']) for item in info['processInfo'] if item['type'] == 'browser'))
            finally:
                await cdp.detach()
        return running
    controller.launch_process = launch
    owns_worker = window is None
    samples, violations, visible_browser_samples = [], [], []
    timer = None
    background_phase = True
    started = datetime(2026, 1, 2, 3, 4, 5)
    try:
        if owns_worker:
            worker.start()
            wait_for(app, lambda: ready)
        if desktop:
            if window is None:
                raise RuntimeError('桌面验收需要可见的主界面')
            import ctypes
            from ctypes import wintypes
            native = ctypes.WinDLL('user32', use_last_error=True)
            native.GetForegroundWindow.restype = wintypes.HWND
            native.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            native.IsWindowVisible.argtypes = [wintypes.HWND]
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            native.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
            def visible_windows():
                handles = []
                @callback_type
                def collect(handle, _):
                    owner = wintypes.DWORD()
                    native.GetWindowThreadProcessId(handle, ctypes.byref(owner))
                    if owner.value in browser_pids and native.IsWindowVisible(handle):
                        handles.append(int(handle))
                    return True
                native.EnumWindows(collect, 0)
                return handles
            def sample():
                if not worker._entered:
                    return
                if background_phase:
                    owner = wintypes.DWORD()
                    native.GetWindowThreadProcessId(native.GetForegroundWindow(), ctypes.byref(owner))
                    samples.append(owner.value)
                    if owner.value in browser_pids or visible_windows():
                        violations.append('后台浏览器显示窗口或抢占前台')
                    if not window.isVisible() or not window.pause_button.isEnabled() or not window.stop_button.isEnabled():
                        violations.append('主界面或运行控制不可用')
                    if window.background.isEnabled() or any(box.isEnabled() for box in window.browser_boxes.values()):
                        violations.append('批次运行配置未锁定')
                elif visible_windows():
                    visible_browser_samples.append(True)
            timer = QTimer()
            timer.timeout.connect(sample)
            timer.start(20)
        with SyntheticSite(media) as site:
            config = SiteConfig(site.origin+'/exam/', str(bundled) if bundled.is_file() else '', 20000, True)
            options = VideoOptions(background=True, video_timeout_seconds=90)
            if window is not None:
                window.background.setChecked(True)
                window.busy = True
                window._controls()
            records_root = output/'records'
            worker.start_job('watch', config, people, str(output/'statistics'), options=options,
                             browsers=choices, started_at=started, outcome_root=records_root)
            if desktop:
                wait_for(app, lambda: worker.last_store and any(r.status == 'watching' for r in worker.last_store.records))
                if not window.isVisible():
                    raise RuntimeError('后台执行时主界面被隐藏')
                window._pause()
                if not worker.control.paused.is_set():
                    raise RuntimeError('后台执行时无法暂停补位')
                window._pause()
                window.grab().save(str(output/'后台执行主界面.png'))
            wait_for(app, lambda: finished, 240)
            if errors:
                raise RuntimeError('; '.join(errors))
            records = list(worker.last_store.records)
            if not all(r.status == 'completed' for r in records):
                raise RuntimeError('视频学习未全部完成：'+repr([(r.status, r.reason) for r in records]))
            round_robin = all(record.browser == choices[index % lane_count].name for index, record in enumerate(records))
            if not round_robin:
                raise RuntimeError('身份未按所选浏览器轮流分配：'+repr([r.browser for r in records]))
            if len(launches) != 12 or not all(running.process.poll() is not None for running in launches):
                raise RuntimeError('未做到每人一个浏览器并在学完后关闭')
            if not 1 <= max(peaks or [0]) <= lane_count:
                raise RuntimeError('并发数超过勾选浏览器数量：'+repr(max(peaks or [0])))
            if len(site.state['learning_visits']) != 12 or site.state['confirmations'] != 12:
                raise RuntimeError('旁听学习或完成确认次数不正确')
            if worker.active_browsers or worker.active_pages:
                raise RuntimeError('批次结束后仍有浏览器未关闭')
            state = json.loads((worker.last_store.folder/'人员状态.json').read_text(encoding='utf-8'))
            expected = {'browsers': [choice.name for choice in choices], 'background': True, 'concurrency': lane_count}
            if state['execution_settings'] != expected or state.get('flow') != 'learning' or state['version'] != 5:
                raise RuntimeError('学习配置没有正确传递到批次')
            completed_book = sorted((records_root/'学习完成').glob('学习完成_*.xlsx'))
            failed_book = sorted((records_root/'学习失败').glob('学习失败_*.xlsx'))
            if len(completed_book) != 1 or len(failed_book) != 1:
                raise RuntimeError('学习完成/失败记录文件数量不正确')
            if not completed_book[0].name.startswith('学习完成_20260102_030405'):
                raise RuntimeError('记录文件没有按启动时间命名：'+completed_book[0].name)
            wb = load_workbook(completed_book[0], read_only=True)
            try:
                outcome_rows = wb.active.max_row == 13 and wb.active.max_column == 3
                headers = [cell.value for cell in next(wb.active.iter_rows(max_row=1))]
            finally:
                wb.close()
            wb = load_workbook(failed_book[0], read_only=True)
            try:
                failed_rows = wb.active.max_row
            finally:
                wb.close()
            if not outcome_rows or headers != ['所在的区县', '姓名', '身份证号'] or failed_rows != 1:
                raise RuntimeError('学习记录格式与导入模板不一致')
            wb = load_workbook(worker.last_store.folder/'已完成信息统计.xlsx', read_only=True)
            try:
                exported = wb.active.max_row == 13 and wb.active.max_column == 13
            finally:
                wb.close()
            learning_launches = list(launches)
            learned = len(site.state['learning_visits'])
            confirmed = site.state['confirmations']
            foreground_mode = False
            if desktop:
                if violations or not samples or not window.isVisible():
                    raise RuntimeError('后台模式验收失败：'+repr(violations[:3]))
                if not window.background.isEnabled() or not window.browser_refresh.isEnabled():
                    raise RuntimeError('批次结束后配置未恢复编辑')
                window.grab().save(str(output/'后台完成主界面.png'))
                background_phase = False
                window.background.setChecked(False)
                window.busy = True
                window._controls()
                worker.start_job('watch', config, people[:1], str(output/'foreground-statistics'),
                                 options=replace(options, background=False), browsers=choices[:1],
                                 started_at=started, outcome_root=output/'foreground-records')
                wait_for(app, lambda: len(finished) == 2, 120)
                foreground_mode = (not errors and launch_modes and launch_modes[-1] is False
                                   and bool(visible_browser_samples)
                                   and worker.last_store.records[0].status == 'completed' and window.isVisible())
                if not foreground_mode:
                    raise RuntimeError('取消后台执行后的可见浏览器流程失败')
                window.background.setChecked(True)
            return dict(identity_import=True, statistics_export=exported, ocr_model=True,
                        browser_launch=True, bundled_browser=bundled.is_file(), learning_flow=True,
                        twelve_full_flows=True, identity_isolation=True,
                        max_active=max(peaks or [0]), completed=len(records), background_execution=True,
                        browser_per_person=len(learning_launches) == 12,
                        browser_closed_after_learning=all(running.process.poll() is not None for running in learning_launches),
                        outcome_files=bool(completed_book and failed_book), outcome_format=outcome_rows and headers == ['所在的区县', '姓名', '身份证号'],
                        browser_round_robin=round_robin, learning_visits=learned,
                        confirmations=confirmed, headless_browser=True,
                        desktop_background=desktop, foreground_mode=foreground_mode,
                        main_window_visible=desktop and window.isVisible(),
                        execution_controls_locked=desktop and not violations,
                        power_request_released=not worker.power_guard.active,
                        background_preserved_foreground=desktop and not violations and bool(samples),
                        foreground_samples=len(samples),
                        no_answering_fields=all(not any(k.startswith('exam_') for k in r) for r in state['records']))
    finally:
        if timer:
            timer.stop()
        controller.launch_process = original_launch
        worker.ocr.recognize = original_recognize
        if owns_worker:
            worker.shutdown()
            wait_for(app, lambda: not worker.isRunning())
