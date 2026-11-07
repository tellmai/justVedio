"""Bounded concurrent scheduling with durable, re-importable results."""
import asyncio
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from .models import Candidate
from .privacy import redact

LABELS = {"pending": "未开始", "running": "正在登录", "watching": "正在学习", "completed": "学习完成", "failed": "失败", "stopped": "已中止"}
ACTIVE_STATUSES = {'running','watching'}
def status_text(record):
    return LABELS[record.status]
def now():
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class PersonResult:
    index: int
    candidate: Candidate
    status: str = "pending"
    reason: str = ""
    started: str = ""
    ended: str = ""
    progress: float = 0
    videos_completed: int = 0
    elapsed_seconds: float = 0
    stage: str = "登录验证"
    browser: str = ""
    already_completed: bool = False


class StatisticsError(RuntimeError):
    pass


def build_records(candidates, rejected=(), prior=None, retry_incomplete=False):
    """Build one deduplicated roster, optionally seeded by today's ledger.

    Rejected duplicate rows whose identity is already represented by a valid
    candidate are dropped so the same person never appears in both the
    completed and failed lists. A completed status from today wins over a
    rejected/failed row; failed/stopped rows stay visible until a retry.
    """
    prior = prior or {}
    candidates = list(candidates)
    valid_ids = {candidate.id_number for candidate in candidates}
    filtered_rejected = []
    seen_rejected = set()
    for candidate, reason in rejected:
        identity = candidate.id_number
        if identity and (identity in valid_ids or identity in seen_rejected):
            continue
        if identity and (prior.get(identity) or {}).get("status") == "completed":
            continue
        if identity:
            seen_rejected.add(identity)
        filtered_rejected.append((candidate, reason))
    pairs = sorted([(c, "") for c in candidates] + filtered_rejected, key=lambda pair: pair[0].row)
    records = []
    for index, (candidate, import_reason) in enumerate(pairs):
        info = prior.get(candidate.id_number) or {}
        status = "failed" if import_reason else "pending"
        reason = import_reason
        stage = "导入失败" if import_reason else "登录验证"
        ended = now() if import_reason else ""
        progress = 0
        already_completed = False
        if info.get("status") == "completed":
            status = "completed"
            reason = "本日已完成，跳过" if info.get("source") != "already" else "已是完成状态，无需再次学习"
            stage = "学习完成"
            ended = info.get("updated") or ended
            progress = 100
            already_completed = info.get("source") == "already"
        elif info.get("status") == "failed" and not retry_incomplete and not import_reason:
            status = "failed"
            reason = info.get("reason") or "本日未完成"
            stage = "登录验证"
            ended = info.get("updated") or ended
        records.append(PersonResult(index, candidate, status, reason, ended=ended,
                                    progress=progress, stage=stage,
                                    already_completed=already_completed))
    return records


class BatchStore:
    def __init__(self, root, candidates, rejected=(), prior=None, retry_incomplete=False):
        self.flow_kind = 'learning'
        self.execution_settings = None
        self.day = None
        self.folder = Path(root).resolve() / f"学习批次_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        self.records = build_records(candidates, rejected, prior, retry_incomplete)

    def update(self, index, persist=True, **changes):
        self.records[index] = replace(self.records[index], **changes)
        if persist:
            self.persist()
        return self.records[index]

    def persist(self):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            target = self.folder / "人员状态.json"
            temporary = target.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump({"version": 5, "application": "justVedio", "flow": self.flow_kind,
                           "day": self.day, "execution_settings": self.execution_settings,
                           "stage": "登录→旁听学习", "updated": now(),
                           "records": [asdict(r) for r in self.records]}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except OSError as error:
            raise StatisticsError("人员状态保存失败，队列已停止，请检查结果目录和磁盘空间") from error
        self.export()

    def export(self):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        try:
            for completed, filename in ((True, "已完成信息统计.xlsx"), (False, "未完成信息统计.xlsx")):
                wb = Workbook()
                try:
                    ws = wb.active
                    ws.title = "流程统计"
                    ws.append(["所在的区县", "姓名", "身份证号", "源文件行号", "状态", "处理阶段", "浏览器", "已完成视频数", "当前视频进度(%)", "观看用时(秒)", "开始时间", "结束时间", "原因"])
                    for r in self.records:
                        if (r.status == "completed") != completed:
                            continue
                        c = r.candidate
                        values = [c.district, c.name, c.id_number, c.row, status_text(r), r.stage, r.browser, r.videos_completed, round(r.progress, 1), round(r.elapsed_seconds, 1), r.started, r.ended, r.reason]
                        ws.append(values)
                        for cell, value in zip(ws[ws.max_row], values):
                            if isinstance(value, str):
                                cell.data_type, cell.number_format = "s", "@"
                    for cell in ws[1]:
                        cell.font = Font(bold=True, color="FFFFFF")
                        cell.fill = PatternFill("solid", fgColor="2464AC")
                    for col, width in zip("ABCDEFGHIJKLM", (18, 18, 26, 12, 18, 22, 18, 18, 22, 20, 24, 24, 65)):
                        ws.column_dimensions[col].width = width
                    ws.freeze_panes, ws.auto_filter.ref = "A2", ws.dimensions
                    target = self.folder / filename
                    temporary = target.with_suffix(".tmp.xlsx")
                    wb.save(temporary)
                    os.replace(temporary, target)
                finally:
                    wb.close()
        except (OSError, ValueError) as error:
            raise StatisticsError("Excel 导出失败，队列已停止；请关闭占用的统计表后重新导出，最新结果保存在 JSON 中") from error


class BatchControl:
    def __init__(self):
        self.paused = threading.Event()
        self.after_current = threading.Event()
        self.immediate = threading.Event()


class BatchRunner:
    def __init__(self, store, control, changed=lambda _: None):
        self.store, self.control, self.changed = store, control, changed

    def update(self, index, **changes):
        try:
            return self.store.update(index, **changes)
        except StatisticsError:
            if changes.get("status") == "running":
                self.store.records[index] = replace(self.store.records[index], status="failed", reason="统计写入失败，未开始浏览器操作", ended=now())
            raise
        finally:
            self.changed(self.store.records[index])

    def _stopped(self):
        return self.control.immediate.is_set() or self.control.after_current.is_set()

    async def _wait_until_allowed(self):
        while self.control.paused.is_set() and not self._stopped():
            await asyncio.sleep(0.05)
        return not self._stopped()

    async def _one(self, perform, index, lane=None):
        candidate = self.store.records[index].candidate
        self.update(index, status="running", started=now())
        try:
            outcome = await (perform(candidate, index, lane) if lane is not None else perform(candidate, index))
        except asyncio.CancelledError:
            self.update(index, status="stopped", reason="用户停止或批次中断，观看结果未确认", ended=now())
            raise
        except StatisticsError:
            raise
        except Exception as error:
            from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
            if isinstance(error, PlaywrightTimeoutError):
                message = "页面操作超时，请检查浏览器窗口是否被遮挡、网络是否稳定"
            elif isinstance(error, PlaywrightError):
                message = "浏览器或页面已关闭，操作失败"
            else:
                message = str(error)
            self.update(index, status="failed", reason=redact(message, (candidate.name, candidate.id_number)), ended=now())
        else:
            outcome = dict(outcome or {})
            already_completed = bool(outcome.pop("already_completed", False))
            browser_closed = bool(outcome.pop("browser_closed", True))
            if already_completed:
                reason = "已是完成状态，无需再次学习"
            elif browser_closed:
                reason = "视频学习完成，浏览器已关闭"
            else:
                reason = "视频学习完成，浏览器保留（停止设置）"
            self.update(index, status="completed", stage="学习完成", reason=reason,
                        progress=100, ended=now(), already_completed=already_completed, **outcome)

    async def _gather(self, tasks):
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # A persistence failure inside perform must not leave phantom active people.
            for r in self.store.records:
                if r.status in ACTIVE_STATUSES:
                    self.store.update(r.index, persist=False, status="stopped", ended=now(), reason="批次中断，结果未确认")
                    self.changed(self.store.records[r.index])
            try:
                self.store.persist()
            except StatisticsError:
                pass
            raise

    async def run(self, perform, concurrency=10):
        """Shared queue with a concurrency limit (used by unit checks)."""
        if not 1 <= concurrency <= 30:
            raise ValueError("并发数须为 1–30")
        self.store.persist()
        pending = [r.index for r in self.store.records if r.status == "pending"]
        if not pending:
            return self.counts()

        async def worker():
            while pending:
                if not await self._wait_until_allowed():
                    return
                index = pending.pop(0)
                await self._one(perform, index)

        tasks = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(pending)))]
        await self._gather(tasks)
        return self.counts()

    async def run_lanes(self, perform, lanes):
        """One worker per browser lane; each lane handles its own people in order."""
        self.store.persist()

        async def lane_worker(lane, indexes):
            for index in indexes:
                if not await self._wait_until_allowed():
                    return
                await self._one(perform, index, lane)

        tasks = [asyncio.create_task(lane_worker(lane, list(indexes)))
                 for lane, indexes in enumerate(lanes) if indexes]
        if tasks:
            await self._gather(tasks)
        return self.counts()

    async def run_workers(self, perform, workers, labels=None, lane_available=None):
        """Keep every selected browser busy with a shared, work-stealing queue.

        A worker that finishes (or fails) a person immediately takes the next
        pending identity instead of waiting for the other lane's original
        people. ``lane_available`` lets the caller retire a lane whose browser
        could not be launched, so it cannot rapidly fail the whole queue.
        """
        self.store.persist()
        pending = [record.index for record in self.store.records if record.status == "pending"]
        cursor = 0

        async def worker(lane):
            nonlocal cursor
            while True:
                if lane_available is not None and not lane_available(lane):
                    return
                if not await self._wait_until_allowed():
                    return
                if cursor >= len(pending):
                    return
                index = pending[cursor]
                cursor += 1
                if labels:
                    self.update(index, browser=labels[lane % len(labels)])
                await self._one(perform, index, lane)
                if lane_available is not None and not lane_available(lane):
                    return

        tasks = [asyncio.create_task(worker(lane)) for lane in range(max(1, workers))]
        await self._gather(tasks)
        return self.counts()

    def counts(self):
        return {s: sum(r.status == s for r in self.store.records) for s in LABELS}
