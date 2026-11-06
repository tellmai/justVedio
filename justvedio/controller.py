import asyncio
from dataclasses import replace
from datetime import datetime
from PySide6.QtCore import QThread, Signal
from .batch import BatchControl, BatchRunner, BatchStore
from .browser import SiteSession, inspect_environment
from .browsers import BrowserChoice, discover_browsers, launch_process
from .learning import LearningFailure, confirm_completion, open_learning, return_home, start_playback, watch_until_complete
from .ocr import LocalOCR
from .privacy import redact
from .records import write_outcomes
from .models import VideoOptions
from .expiry import ensure_active, is_expired, EXPIRY_MESSAGE
from .background import PowerGuard


class BrowserWorker(QThread):
    ready = Signal()
    progress = Signal(str)
    failed = Signal(str)
    completed = Signal(str)
    job_finished = Signal()
    batch_started = Signal(str, object)
    person_updated = Signal(object)
    batch_finished = Signal(object)
    check_result = Signal(str, bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loop = self.task = None
        self.control = BatchControl()
        self.ocr = LocalOCR()
        self.active_pages = {}
        self.active_browsers = {}
        self.last_store = None
        self.secrets = ()
        self._closing = self._preserve = self._entered = False
        self.browser_background = True
        self.power_guard = PowerGuard()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._lifetime())
        except Exception:
            self.failed.emit("浏览器控制模块初始化失败，请检查运行依赖")
        finally:
            self.power_guard.release()
            self.ocr.close()
            self.loop.close()

    async def _lifetime(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as self.playwright:
            self.exit_event = asyncio.Event()
            self.ready.emit()
            if self._closing:
                self.exit_event.set()
            expiry_watch=asyncio.create_task(self._watch_expiry())
            try:
                await self.exit_event.wait()
            finally:
                expiry_watch.cancel()
                await asyncio.gather(expiry_watch,return_exceptions=True)
            if self.task and not self.task.done():
                self.control.immediate.set()
                if self._entered:
                    self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            await self._cleanup()

    async def _watch_expiry(self):
        while not is_expired():
            await asyncio.sleep(1)
        self._closing=True
        self.failed.emit(EXPIRY_MESSAGE)
        self.exit_event.set()

    async def _cleanup(self):
        """Close browsers unless the application is exiting (they then survive)."""
        if self._preserve:
            self.active_pages.clear()
            self.active_browsers.clear()
        else:
            for running in list(self.active_browsers.values()):
                try:
                    await running.close()
                except Exception:
                    pass
            self.active_browsers.clear()
            self.active_pages.clear()

    def start_job(self, kind, config, candidates=(), output_root="results", rejected=(), options=None,
                  browsers=(), started_at=None, outcome_root=None):
        self.control = BatchControl()
        self._entered = False
        def schedule():
            if not self.task or self.task.done():
                self.task = self.loop.create_task(self._execute(
                    kind, config, list(candidates), output_root, rejected, options,
                    list(browsers), started_at or datetime.now(), outcome_root))
        self.loop.call_soon_threadsafe(schedule)

    @staticmethod
    def _choices(config, browsers):
        if browsers:
            return list(browsers)
        if config.chrome_path:
            return [BrowserChoice("手动指定浏览器", config.chrome_path, -1)]
        return discover_browsers()[:1]

    async def _execute(self, kind, config, candidates, output_root, rejected, options, browsers, started_at, outcome_root):
        self._entered = True
        self.secrets = tuple(value for c in candidates for value in (c.name, c.id_number))
        runner = None
        store = None
        try:
            ensure_active()
            await self._cleanup()
            if kind == "export":
                if self.last_store:
                    self.last_store.persist()
                    self.completed.emit("本批次结果已重新导出")
            elif kind == "inspect":
                ok = await inspect_environment(self.playwright, config, self.ocr, candidates[0].district if candidates else "", self.check_result.emit)
                self.completed.emit("环境检测通过" if ok else "环境检测发现问题")
            else:
                options = options or VideoOptions()
                config.validate()
                choices = self._choices(config, browsers)
                if not choices:
                    raise ValueError("未找到可用浏览器，请安装 Chrome / Edge，或在运行配置中勾选浏览器")
                options = replace(options, concurrency=max(1, len(choices)))
                options.validate_execution()
                for value, label in ((options.learning_entry_text, "学习入口文字"),
                                     (options.confirm_text, "完成确认文字"),
                                     (options.home_text, "返回主页文字"),
                                     (options.video_selector, "视频元素")):
                    if not str(value or '').strip():
                        raise ValueError(f"{label}不能为空")
                store = self.last_store = BatchStore(output_root, candidates, rejected)
                store.flow_kind = 'learning'
                store.execution_settings = {'browsers': [c.name for c in choices], 'background': options.background, 'concurrency': len(choices)}
                store.persist()
                if self.control.immediate.is_set():
                    return
                pending = [r.index for r in store.records if r.status == 'pending']
                if not pending:
                    self.batch_started.emit(str(store.folder), list(store.records))
                    self.completed.emit("本批次没有可执行身份，全部记录已保存")
                    return
                self.power_guard.acquire()
                self.browser_background = options.background
                lanes = [[] for _ in choices]
                for position, index in enumerate(pending):
                    lane = position % len(choices)
                    lanes[lane].append(index)
                    store.update(index, persist=False, browser=choices[lane].name)
                store.persist()
                self.batch_started.emit(str(store.folder), list(store.records))
                self._progress(f"共 {len(pending)} 人，按 {len(choices)} 路并发：{'、'.join(c.name for c in choices)}")
                runner = BatchRunner(store, self.control, self.person_updated.emit)

                async def perform(candidate, index, lane_index):
                    ensure_active()
                    choice = choices[lane_index]
                    def report(text):
                        self._progress(f"第 {candidate.row} 行：{text}")
                    running = await launch_process(self.playwright, choice, headless=options.background, progress=self._progress)
                    self.active_browsers[index] = running
                    try:
                        context = running.browser.contexts[0] if running.browser.contexts else await running.browser.new_context()
                        page = context.pages[0] if context.pages else await context.new_page()
                        self.active_pages[index] = page
                        page.on('dialog', lambda dialog: asyncio.ensure_future(dialog.accept()))
                        session = SiteSession(self.playwright, config, report, browser=running.browser, context=context, page=page)
                        try:
                            await asyncio.wait_for(session.login(candidate, self.ocr), options.login_timeout_seconds)
                        except TimeoutError:
                            raise ValueError("登录验证超过最长等待时间") from None
                        ensure_active()
                        home_url = page.url
                        runner.update(index, status="watching", stage="旁听学习", reason="登录成功，正在进入旁听学习")
                        study_page = await open_learning(page, options, report)
                        if study_page is None:
                            raise LearningFailure("未找到“开始旁听学习/继续旁听学习”入口，已记为失败")
                        if study_page is not page:
                            page = study_page
                            self.active_pages[index] = page
                        video = await start_playback(page, options, report)
                        runner.update(index, persist=False, stage="视频学习", reason="视频正在播放，等待学习完成")
                        def update(**changes):
                            runner.update(index, persist=False, **changes)
                        await watch_until_complete(page, video, options, update, report, browser=running.browser, home_url=home_url)
                        runner.update(index, persist=False, stage="确认学习完成", reason="视频已播放结束，正在确认并返回主页")
                        await confirm_completion(page, options, report)
                        if not await return_home(page, options, home_url, report):
                            raise LearningFailure("学习完成后未能返回考生主页，未记为完成")
                        runner.update(index, persist=False, stage="关闭浏览器")
                        if not await running.close():
                            raise LearningFailure("学习完成后浏览器未能关闭，未记为完成")
                        self.active_browsers.pop(index, None)
                        self.active_pages.pop(index, None)
                        self._progress(f"第 {candidate.row} 行：已检测到浏览器关闭，学习完成")
                        return {}
                    finally:
                        self.active_browsers.pop(index, None)
                        self.active_pages.pop(index, None)
                        if not self._preserve and running.is_open():
                            try:
                                await running.close()
                            except Exception:
                                pass

                counts = await runner.run_lanes(perform, lanes)
                self.completed.emit(f"本批次结束：学习完成 {counts['completed']} 人，失败 {counts['failed']} 人，中止 {counts['stopped']} 人，未开始 {counts['pending']} 人；浏览器已按人关闭")
        except asyncio.CancelledError:
            self._progress("已立即停止，正在关闭当前身份浏览器；未确认的步骤不会记为完成")
        except Exception as error:
            from playwright.async_api import Error as PlaywrightError
            self.failed.emit("浏览器操作失败，请检查浏览器与网络" if isinstance(error, PlaywrightError) else redact(str(error), self.secrets))
        finally:
            cleanup = asyncio.create_task(self._cleanup())
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            try:
                cleanup.result()
            except Exception:
                self.failed.emit("部分浏览器资源关闭失败，请检查浏览器窗口")
            if runner and not self._preserve:
                try:
                    targets = write_outcomes(list(store.records), started_at, base=outcome_root)
                    self._progress(f"学习记录已保存：{targets['completed']}；{targets['failed']}")
                except Exception:
                    self._progress("学习记录写入失败，请检查软件目录是否可写")
            if runner:
                self.batch_finished.emit(runner.counts())
            self.power_guard.release()
            self.secrets = ()
            self._entered = False
            self.job_finished.emit()

    def _progress(self, text):
        self.progress.emit(redact(text, self.secrets))

    def pause_queue(self):
        self.control.paused.set()

    def resume_queue(self):
        self.control.paused.clear()

    def stop_after_current(self):
        self.control.after_current.set()
        self.control.paused.clear()

    def stop_job(self):
        self.control.immediate.set()
        self.control.paused.clear()
        def cancel():
            if self.task and not self.task.done() and self._entered:
                self.task.cancel()
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(cancel)

    def focus(self, index):
        async def bring():
            page = self.active_pages.get(index)
            if page is None or page.is_closed():
                self._progress("该身份学习已结束或浏览器已关闭")
                return
            if self.browser_background:
                self._progress('本批次为后台执行，浏览器保持隐藏；请在主界面查看进度和结果')
                return
            try:
                await page.bring_to_front()
            except Exception:
                self._progress("该身份网页已关闭")
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(lambda: self.loop.create_task(bring()))

    def begin_shutdown(self):
        """Stop the queue but leave in-flight browsers running (app exit)."""
        self._preserve = True
        self._closing = True
        self._finish_loop()

    def shutdown(self):
        """Stop the queue and close every browser (tests and scripts)."""
        self._preserve = False
        self._closing = True
        self._finish_loop()

    def _finish_loop(self):
        self.control.immediate.set()
        self.control.paused.clear()
        def finish():
            if self.task and not self.task.done() and self._entered:
                self.task.cancel()
            if hasattr(self, "exit_event"):
                self.exit_event.set()
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(finish)
