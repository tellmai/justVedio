import asyncio
from dataclasses import replace
from PySide6.QtCore import QThread, Signal
from .batch import BatchControl, BatchRunner, BatchStore
from .browser import SiteSession, inspect_environment
from .browsers import launch_browser
from .browser_pages import BrowserPages
from .local_video import LocalVideoServer
from .ocr import LocalOCR
from .privacy import redact
from .video import watch_playlist
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
        self.sessions = {}
        self.retained_sessions = {}
        self.retained_browser = None
        self.browser = self.video_server = self.last_store = None
        self.secrets = ()
        self._closing = self._entered = False
        self.browser_background = self.retained_background = True
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

    async def _cleanup(self,preserve_retained=False):
        await asyncio.gather(*(s.close() for s in self.sessions.values()), return_exceptions=True)
        self.sessions.clear()
        if preserve_retained and self.retained_sessions and self.browser:
            self.retained_browser,self.browser=self.browser,None
            self.retained_background = self.browser_background
        if self.browser:
            browser = self.browser
            await browser.close()
            self.browser = None
        if not preserve_retained:
            await asyncio.gather(*(s.close() for s in self.retained_sessions.values()),return_exceptions=True)
            self.retained_sessions.clear()
            if self.retained_browser:
                browser = self.retained_browser
                await browser.close()
                self.retained_browser=None
        if self.video_server:
            server, self.video_server = self.video_server, None
            await asyncio.to_thread(server.close)

    def start_job(self, kind, config, candidates=(), output_root="results", rejected=(), options=None, test_mode=False):
        self.control = BatchControl()
        self._entered = False
        def schedule():
            if not self.task or self.task.done():
                self.task = self.loop.create_task(self._execute(kind, config, list(candidates), output_root, rejected, options, test_mode))
        self.loop.call_soon_threadsafe(schedule)

    async def _execute(self, kind, config, candidates, output_root, rejected, options, test_mode=False):
        self._entered = True
        self.secrets = tuple(value for c in candidates for value in (c.name, c.id_number))
        runner = None
        try:
            ensure_active()
            if kind!='export':
                await self._cleanup()
            if kind == "export":
                if self.last_store:
                    self.last_store.persist()
                    self.completed.emit("本批次结果已重新导出")
            elif kind == "inspect":
                ok = await inspect_environment(self.playwright, config, self.ocr, candidates[0].district if candidates else "", self.check_result.emit)
                self.completed.emit("环境检测通过" if ok else "环境检测发现问题")
            else:
                options=options or VideoOptions()
                config.validate()
                options.validate_execution()
                if test_mode:
                    options.validate(config)
                store = self.last_store = BatchStore(output_root, candidates, rejected)
                store.flow_kind='test' if test_mode else 'login'
                store.execution_settings = {'concurrency': options.concurrency, 'background': options.background}
                runner = BatchRunner(store, self.control, self.person_updated.emit)
                self.batch_started.emit(str(store.folder), list(store.records))
                store.persist()
                if self.control.immediate.is_set():
                    return
                self.power_guard.acquire()
                self.browser_background = options.background
                self.browser, _ = await launch_browser(self.playwright, config.chrome_path,
                                                      headless=options.background, progress=self._progress)
                self._progress('本批次后台执行，浏览器隐藏，主界面继续显示进度' if options.background else '本批次显示浏览器窗口')
                pages = BrowserPages(self.browser)
                if test_mode and options.mode == "local":
                    self.video_server = LocalVideoServer(options.local_file)
                session_gate=asyncio.Lock()
                async def perform(candidate, index):
                    ensure_active()
                    session = SiteSession(self.playwright, config, lambda text: self._progress(f"第 {candidate.row} 行：{text}"), browser=self.browser, pages=pages)
                    login_succeeded=False
                    async with session_gate:
                        while not test_mode and self.retained_sessions and len(self.sessions)+len(self.retained_sessions)>=options.concurrency:
                            oldest=next(iter(self.retained_sessions))
                            await self.retained_sessions.pop(oldest).close()
                        self.sessions[index] = session
                    try:
                        try:
                            await asyncio.wait_for(session.login(candidate, self.ocr), options.login_timeout_seconds)
                        except TimeoutError:
                            raise ValueError("登录验证超过最长等待时间") from None
                        ensure_active()
                        if not test_mode:
                            runner.update(index,stage='登录验证完成',reason='登录验证成功，保留登录后主页供查看')
                            login_succeeded=True
                            return {}
                        runner.update(index, status="watching", stage='视频观看', reason='登录验证成功，正在打开视频')
                        video_options = options
                        if options.mode == "local":
                            await session.page.goto(self.video_server.url, wait_until="domcontentloaded")
                            video_options = replace(options, frame_selector="", video_selector="video", play_selector="#play", complete_selector="#completed", next_selector="")
                        else:
                            if options.video_url:
                                await session.page.goto(options.video_url, wait_until="domcontentloaded")
                            if options.entry_selector:
                                await session.page.locator(options.entry_selector).first.click()
                        def update(**changes):
                            # Progress is live in the UI; durable writes occur at stage/end.
                            runner.update(index, persist=False, **changes)
                        return await watch_playlist(session.page, video_options, update)
                    finally:
                        async with session_gate:
                            self.sessions.pop(index,None)
                            if not test_mode and login_succeeded:
                                self.retained_sessions[index]=session
                            else:
                                await session.close()
                counts = await runner.run(perform, options.concurrency)
                label='测试全流程完成' if test_mode else '登录验证完成'
                suffix='' if test_mode else f'；保留最近 {len(self.retained_sessions)} 个登录后会话' + ('（后台会话保持隐藏）' if options.background else '供查看')
                self.completed.emit(f"本批次结束：{label} {counts['completed']} 人，失败 {counts['failed']} 人，中止 {counts['stopped']} 人，未开始 {counts['pending']} 人{suffix}")
        except asyncio.CancelledError:
            self._progress("已立即停止，正在释放当前身份会话；未确认的步骤不会记为完成")
        except Exception as error:
            from playwright.async_api import Error as PlaywrightError
            self.failed.emit("浏览器操作失败，请检查浏览器与网络" if isinstance(error, PlaywrightError) else redact(str(error), self.secrets))
        finally:
            keep_login_pages=(kind=='export' or kind=='watch' and not test_mode) and not self._closing
            cleanup = asyncio.create_task(self._cleanup(preserve_retained=keep_login_pages))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            try:
                cleanup.result()
            except Exception:
                self.failed.emit("部分浏览器资源关闭失败，请检查浏览器窗口")
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
            try:
                session = self.sessions.get(index) or self.retained_sessions.get(index)
                if session and session.page:
                    background = self.browser_background if index in self.sessions else self.retained_background
                    if background:
                        self._progress('本批次为后台执行，浏览器保持隐藏；请在主界面查看进度和结果')
                        return
                    await (getattr(session,'active_page',None) or session.page).bring_to_front()
            except Exception:
                self._progress("该身份网页已关闭")
        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(bring()))

    def shutdown(self):
        self._closing = True
        if self.loop and not self.loop.is_closed() and hasattr(self, "exit_event"):
            self.loop.call_soon_threadsafe(self.exit_event.set)
