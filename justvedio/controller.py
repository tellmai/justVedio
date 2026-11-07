import asyncio
from dataclasses import replace
from datetime import datetime
from PySide6.QtCore import QThread, Signal
from .batch import BatchControl, BatchRunner, BatchStore
from .browser import SiteSession, inspect_environment
from .browsers import BrowserChoice, discover_browsers, launch_process
from .daily import day_key, load_day, record_person
from .learning import (LearningFailure, confirm_completion, is_learning_completed, open_learning,
                       return_home, start_playback, verify_learning_completed,
                       watch_until_complete)
from .ocr import LocalOCR
from .privacy import redact
from .records import write_daily_outcomes
from .models import VideoOptions
from .expiry import is_expired
from .totals import load_completed_learning, record_completed_learning
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
    lifetime_updated = Signal(int)

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
        self._unavailable_lanes = set()
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
        self._closing = True
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
        # A previous stop/app exit deliberately left its browsers open. Old
        # processes are no longer tracked, so a new batch manages only itself.
        self._preserve = False
        self._unavailable_lanes = set()
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
            if is_expired():
                return
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
                day = day_key(started_at)
                try:
                    prior = load_day(day)
                except Exception:
                    prior = {}
                store = self.last_store = BatchStore(output_root, candidates, rejected,
                                                     prior=prior, retry_incomplete=True)
                store.day = day
                store.flow_kind = 'learning'
                store.execution_settings = {'browsers': [c.name for c in choices], 'background': options.background, 'concurrency': len(choices)}
                store.persist()
                if self.control.immediate.is_set():
                    return
                pending = [r.index for r in store.records if r.status == 'pending']
                if not pending:
                    self.batch_started.emit(str(store.folder), list(store.records))
                    self.completed.emit("本日没有需要执行的身份，全部记录已保存")
                    return
                self.power_guard.acquire()
                self.browser_background = options.background
                self.batch_started.emit(str(store.folder), list(store.records))
                self._progress(f"本日待学习 {len(pending)} 人，{len(choices)} 个浏览器持续补位：{'、'.join(c.name for c in choices)}")
                def changed(record):
                    try:
                        record_person(record, day)
                    except Exception:
                        pass
                    self.person_updated.emit(record)
                runner = BatchRunner(store, self.control, changed)

                async def perform(candidate, index, lane_index):
                    if is_expired():
                        raise asyncio.CancelledError
                    choice = choices[lane_index]
                    def report(text):
                        self._progress(f"第 {candidate.row} 行：{text}")
                    try:
                        running = await launch_process(self.playwright, choice,
                                                       headless=options.background,
                                                       progress=self._progress)
                    except Exception:
                        # Do not let a broken browser lane consume the shared
                        # queue and rapidly mark every remaining person failed.
                        self._unavailable_lanes.add(lane_index)
                        raise
                    self.active_browsers[index] = running
                    try:
                        # Edge can open its first-run/privacy page in an extra
                        # window. Keep one normal page and close the rest so
                        # every lane operates exactly one browser window.
                        contexts = list(running.browser.contexts)
                        if contexts:
                            context = next(
                                (item for item in contexts
                                 if any(page.url == 'about:blank' for page in item.pages)),
                                next((item for item in contexts if item.pages), contexts[0]))
                            for extra_context in contexts:
                                if extra_context is not context:
                                    try:
                                        await extra_context.close()
                                    except Exception:
                                        pass
                        else:
                            context = await running.browser.new_context()
                        pages = list(context.pages)
                        page = (next((item for item in pages if item.url == 'about:blank'), pages[0])
                                if pages else await context.new_page())
                        for extra_page in pages:
                            if extra_page is page:
                                continue
                            try:
                                await extra_page.close()
                            except Exception:
                                pass
                        self.active_pages[index] = page
                        page.on('dialog', lambda dialog: asyncio.ensure_future(dialog.accept()))
                        session = SiteSession(self.playwright, config, report, browser=running.browser, context=context, page=page)
                        try:
                            await asyncio.wait_for(session.login(candidate, self.ocr), options.login_timeout_seconds)
                        except TimeoutError:
                            raise ValueError("登录验证超过最长等待时间") from None
                        if is_expired():
                            raise asyncio.CancelledError
                        home_url = page.url
                        if await is_learning_completed(page, options, timeout=8):
                            runner.update(index, persist=False, stage="已确认完成",
                                          reason="登录后显示“再次考试/本年度网考已完成”，跳过学习")
                            self._progress(f"第 {candidate.row} 行：登录后已是完成状态，跳过本次学习")
                            browser_closed = True
                            if self._preserve:
                                browser_closed = False
                            else:
                                try:
                                    browser_closed = await running.close()
                                except Exception:
                                    browser_closed = False
                            self.active_browsers.pop(index, None)
                            self.active_pages.pop(index, None)
                            return {'already_completed': True, 'browser_closed': browser_closed}
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
                        if not await confirm_completion(page, options, report):
                            raise LearningFailure("视频结束后未找到并点击“确认完成”，未记为完成")
                        if not await return_home(page, options, home_url, report):
                            raise LearningFailure("未能点击“返回考生主页”或返回后仍显示旁听/进入考试入口，未记为完成")
                        await verify_learning_completed(page, options, report)
                        hold = options.post_completion_wait_seconds
                        if hold > 0:
                            runner.update(index, persist=False, stage="等待关闭浏览器",
                                          reason=f"已确认学习完成，停留 {hold:g} 秒后关闭浏览器")
                            report(f'已确认学习完成，停留 {hold:g} 秒后关闭浏览器')
                            await asyncio.sleep(hold)
                        browser_closed = True
                        if self._preserve:
                            browser_closed = False
                            runner.update(index, persist=False, stage="学习完成，保留浏览器",
                                          reason="已确认学习完成；按停止设置保留浏览器")
                            self._progress(f"第 {candidate.row} 行：已确认学习完成，按停止设置保留浏览器")
                        else:
                            runner.update(index, persist=False, stage="关闭浏览器")
                            if not await running.close():
                                raise LearningFailure("学习完成后浏览器未能关闭，未记为完成")
                            self._progress(f"第 {candidate.row} 行：已检测到浏览器关闭，学习完成")
                        self.active_browsers.pop(index, None)
                        self.active_pages.pop(index, None)
                        completed_total = None
                        try:
                            completed_total = record_completed_learning()
                        except Exception:
                            pass
                        if completed_total is not None:
                            self.lifetime_updated.emit(completed_total)
                            self._progress(f"累计完成学习 {completed_total} 人次")
                        return {'browser_closed': browser_closed}
                    finally:
                        self.active_browsers.pop(index, None)
                        self.active_pages.pop(index, None)
                        if not self._preserve and running.is_open():
                            try:
                                await running.close()
                            except Exception:
                                pass

                counts = await runner.run_workers(
                    perform, len(choices), labels=[choice.name for choice in choices],
                    lane_available=lambda lane: lane not in self._unavailable_lanes)
                try:
                    completed_total = load_completed_learning()
                except Exception:
                    completed_total = None
                summary = (f"本日学习结束：已完成 {counts['completed']} 人，失败 {counts['failed']} 人，"
                           f"中止 {counts['stopped']} 人，未开始 {counts['pending']} 人；"
                           + ("已按停止设置保留浏览器" if self._preserve else "浏览器已按人关闭"))
                if completed_total is not None:
                    summary += f"；累计完成学习 {completed_total} 人次"
                self.completed.emit(summary)
        except asyncio.CancelledError:
            self._progress("已立即停止；已打开的浏览器会保留，未确认的步骤不会记为完成")
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
            if store:
                try:
                    targets = write_daily_outcomes(list(store.records), started_at, base=outcome_root)
                    self._progress(f"本日学习记录已保存：{targets['completed']}；{targets['failed']}")
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
        # Stopping a batch must not close browsers that are already open.
        self._preserve = True
        self.control.after_current.set()
        self.control.paused.clear()

    def stop_job(self):
        self._preserve = True
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
