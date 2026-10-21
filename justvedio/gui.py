import logging
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QThread, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QApplication, QScrollArea)
from .controller import BrowserWorker
from .models import DEFAULT_URL, DEFAULT_VIDEO_URL, SiteConfig, VideoOptions
from .importers import load_identities
from .privacy import redact
from .batch import LABELS, ACTIVE_STATUSES, status_text
from .version import APP_NAME, VERSION
from .settings import application_settings
from .expiry import is_expired, EXPIRY_MESSAGE, VALID_THROUGH


class ImportWorker(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
    def run(self):
        try:
            result = load_identities(self.path)
            if self.isInterruptionRequested():
                raise InterruptedError('已停止文件导入')
            self.result.emit(result)
        except Exception as error:
            self.failed.emit(redact(str(error)) if isinstance(error, (ValueError,InterruptedError)) else "文件读取失败，请检查格式和访问权限")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = application_settings()
        self.candidates, self.rejected, self.batch_records = [], [], []
        self.import_worker = None
        self.busy = self.backend_ready = self._closing = self._allow_close = False
        self.result_folder = ""
        self.batch_test_mode = None
        self._expiry_notified = False
        self.setWindowTitle(f"{APP_NAME} v{VERSION} · 有效期至 {VALID_THROUGH}")
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, available.width()), min(900, available.height()))
        resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        self.setWindowIcon(QIcon(str(resources / 'justvedio/assets/app.ico')))
        self._build_ui()
        self.backend = BrowserWorker(self)
        self.backend.ready.connect(self._ready)
        self.backend.progress.connect(self.show_status)
        self.backend.failed.connect(lambda text: self.show_status("失败：" + text))
        self.backend.completed.connect(self.show_status)
        self.backend.batch_started.connect(self._batch_started)
        self.backend.person_updated.connect(self._person_updated)
        self.backend.batch_finished.connect(lambda _: self._render())
        self.backend.job_finished.connect(self._finished)
        self.backend.check_result.connect(lambda label, ok, detail: self.show_status(f"{label}：{'通过' if ok else '未通过'} · {detail}"))
        self.backend.finished.connect(self._backend_finished)
        self.backend.start()
        self._controls()
        self.expiry_timer=QTimer(self)
        self.expiry_timer.timeout.connect(self._check_expiry)
        self.expiry_timer.start(1000)

    def _check_expiry(self):
        if not is_expired():
            return False
        if not self._expiry_notified:
            self._expiry_notified=True
            self.expiry_timer.stop()
            self.close()
            QMessageBox.critical(self,'软件已过期',EXPIRY_MESSAGE)
        return True

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size:24px;font-weight:600;color:#173457")
        layout.addWidget(title)
        layout.addWidget(QLabel("导入身份 → 登录验证 → 视频观看 → 保存结果 → 自动补位"))
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setWidget(settings_widget)
        self.settings_scroll.setFrameShape(QScrollArea.NoFrame)
        self.settings_scroll.setMaximumHeight(min(430, int(QApplication.primaryScreen().availableGeometry().height() * .48)))
        layout.addWidget(self.settings_scroll)
        site = QGroupBox("登录与结果")
        form = QFormLayout(site)
        self.url = QLineEdit(self.settings.value("url", DEFAULT_URL))
        self.chrome = QLineEdit(self.settings.value("chrome", ""))
        self.chrome.setPlaceholderText("自动查找 Chrome / Edge；也可填写浏览器 exe 路径")
        self.chrome_button = QPushButton("选择浏览器")
        self.chrome_button.clicked.connect(self._choose_chrome)
        row = QHBoxLayout()
        row.addWidget(self.chrome, 1)
        row.addWidget(self.chrome_button)
        form.addRow("登录入口", self.url)
        form.addRow("浏览器", row)
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        self.output = QLineEdit(self.settings.value("output", str(base / "results")))
        self.output_button = QPushButton("选择目录")
        self.output_button.clicked.connect(self._choose_output)
        row = QHBoxLayout()
        row.addWidget(self.output, 1)
        row.addWidget(self.output_button)
        form.addRow("结果目录", row)
        settings_layout.addWidget(site)
        self.test_mode=QCheckBox('启动测试：登录后直接观看测试视频')
        self.test_mode.setObjectName('testModeSwitch')
        self.test_mode.setChecked(False)
        self.test_mode.setToolTip('仅切换执行流程：关闭时只验证登录并保留主页；开启后登录成功直接播放视频。视频设置始终可提前配置。')
        self.test_mode.toggled.connect(self._controls)
        flow = QGroupBox('全局流程设置')
        flow.setObjectName('globalFlowSettings')
        flow_form = QFormLayout(flow)
        flow_form.addRow(self.test_mode)
        self.concurrency = QSpinBox()
        self.concurrency.setObjectName('flowConcurrency')
        self.concurrency.setRange(1, 30)
        self.concurrency.setValue(int(self.settings.value('concurrency', 10)))
        self.concurrency.setToolTip('每个身份从登录到所选流程结束共占一个名额，完成或失败后自动接入下一位。')
        self.background = QCheckBox('后台执行（隐藏浏览器）')
        self.background.setObjectName('backgroundExecution')
        self.background.setChecked(self.settings.value('background', True, type=bool))
        self.background.setToolTip('仅隐藏本批次浏览器，主界面继续显示进度、日志及暂停/停止操作。取消勾选后可观察浏览器；设置在批次启动时生效。')
        row = QHBoxLayout()
        row.addWidget(self.concurrency)
        row.addWidget(self.background)
        flow_note = QLabel('个身份同时执行所选流程；结束后自动补位（登录 → 视频）')
        flow_note.setWordWrap(True)
        row.addWidget(flow_note, 1)
        flow_form.addRow('全局并发数量', row)
        settings_layout.addWidget(flow)
        self.flow_settings = QTabWidget()
        video = QGroupBox("视频观看")
        form = QFormLayout(video)
        self.mode = QComboBox()
        self.mode.addItem("测试：登录后打开指定视频网址", "url")
        self.mode.addItem("正式：登录后点击原网站内的视频链接", "link")
        self.mode.setCurrentIndex(int(self.settings.value("mode", 0)))
        self.video_url = QLineEdit(self.settings.value("video_url", DEFAULT_VIDEO_URL))
        self.entry = QLineEdit(self.settings.value("entry", ""))
        self.entry.setPlaceholderText("例如 a[href='/exam/user/video']；也支持 text=观看视频")
        form.addRow("观看入口", self.mode)
        form.addRow("测试视频网址", self.video_url)
        form.addRow("站内入口选择器", self.entry)
        row = QHBoxLayout()
        self.muted = QCheckBox("静音播放")
        self.muted.setChecked(self.settings.value("muted", True, type=bool))
        row.addWidget(self.muted)
        row.addStretch()
        form.addRow("播放选项", row)
        self.advanced_toggle = QCheckBox("高级设置：播放器选择器与超时")
        form.addRow(self.advanced_toggle)
        advanced = QWidget()
        extra = QFormLayout(advanced)
        self.media = QLineEdit(self.settings.value("media", "video, bwp-video"))
        self.play = QLineEdit(self.settings.value("play", ""))
        self.play.setPlaceholderText("留空点击视频播放；可指定播放按钮")
        self.frame = QLineEdit(self.settings.value("frame", ""))
        self.complete = QLineEdit(self.settings.value("complete", ""))
        self.next_video = QLineEdit(self.settings.value("next", ""))
        self.video_timeout = QSpinBox()
        self.video_timeout.setRange(1, 720)
        self.video_timeout.setValue(int(self.settings.value("video_timeout", 120)))
        self.stall_timeout = QSpinBox()
        self.stall_timeout.setRange(5, 1800)
        self.stall_timeout.setValue(int(self.settings.value("stall_timeout", 120)))
        for label, widget in (("视频元素", self.media), ("播放按钮", self.play), ("视频 iframe", self.frame), ("平台完成标志（可选）", self.complete), ("下一视频按钮（可选）", self.next_video), ("单视频最长等待（分钟）", self.video_timeout), ("停滞超时（秒）", self.stall_timeout)):
            extra.addRow(label, widget)
        form.addRow(advanced)
        advanced.hide()
        self.advanced_toggle.toggled.connect(advanced.setVisible)
        self.mode.currentIndexChanged.connect(self._controls)
        self.flow_settings.addTab(video,'视频观看设置')
        settings_layout.addWidget(self.flow_settings)
        row = QHBoxLayout()
        self.import_button = QPushButton("导入身份 Excel")
        self.import_button.clicked.connect(self._choose_file)
        self.template_button = QPushButton("保存身份表模板")
        self.template_button.clicked.connect(self._save_template)
        self.identity_summary = QLabel("需包含：所在的区县、姓名、身份证号；身份证号请使用文本格式")
        row.addWidget(self.import_button)
        row.addWidget(self.template_button)
        row.addWidget(self.identity_summary, 1)
        layout.addLayout(row)
        self.counts = QLabel("尚未开始")
        layout.addWidget(self.counts)
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(180)
        self.tables = {}
        for key, label in (("all", "全部身份"), ("active", "正在登录 / 观看"), ("completed", "已完成"), ("failed", "失败 / 中止")):
            table = QTableWidget(0, 8)
            table.setHorizontalHeaderLabels(["行号", "区县", "姓名", "身份证号（脱敏）", "状态", "当前步骤进度", "已完成视频", "结果 / 原因"])
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            table.horizontalHeader().setStretchLastSection(True)
            table.verticalHeader().hide()
            table.cellDoubleClicked.connect(lambda row, col, t=table: self._focus(t, row))
            self.tables[key] = table
            self.tabs.addTab(table, label)
        layout.addWidget(self.tabs, 1)
        row = self.action_bar = QHBoxLayout()
        self.start_button = QPushButton("启动完整流程")
        self.start_button.setObjectName("startWatch")
        self.inspect_button = QPushButton("环境检测")
        self.pause_button = QPushButton("暂停补位")
        self.stop_button = QPushButton("停止")
        self.start_button.clicked.connect(lambda: self._start("watch"))
        self.inspect_button.clicked.connect(lambda: self._start("inspect"))
        self.pause_button.clicked.connect(self._pause)
        self.stop_button.clicked.connect(self._stop)
        for button in (self.inspect_button, self.start_button, self.pause_button, self.stop_button):
            button.setMinimumHeight(34)
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.result_location = QLabel("每批次保存已完成 / 未完成 Excel 和 JSON；双击正在进行的身份可查看网页")
        self.result_location.setTextFormat(Qt.PlainText)
        self.result_location.setWordWrap(True)
        self.export_button = QPushButton("重新导出")
        self.open_button = QPushButton("打开结果目录")
        self.export_button.clicked.connect(lambda: self._start("export"))
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.result_folder)))
        row.addWidget(self.result_location, 1)
        row.addWidget(self.export_button)
        row.addWidget(self.open_button)
        layout.addLayout(row)
        self.status = QLabel("正在初始化浏览器控制模块…")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setMaximumHeight(85)
        layout.addWidget(self.log)
        self.setStyleSheet("""QMainWindow{background:#f2f5fa}QGroupBox{background:white;border:1px solid #d6dfeb;border-radius:6px;margin-top:12px;padding:12px 8px 8px;font-weight:600}QGroupBox::title{subcontrol-origin:margin;left:12px}QPushButton{padding:6px 12px;border:1px solid #b7c8dc;border-radius:4px;background:#edf3fb}QPushButton:hover{background:#dbe9f9}QPushButton:disabled{color:#8796a7}QPushButton#startWatch{background:#2464ac;color:white}QPushButton#startWatch:disabled{background:#a7bcd5}QLineEdit,QPlainTextEdit,QTableWidget{background:white;border:1px solid #d1dbe7;padding:4px}QLabel{color:#263b53}""")

    def _video_controls(self):
        self.video_url.setEnabled(not self.busy and self.mode.currentData() == "url")
        self.entry.setEnabled(not self.busy and self.mode.currentData() == "link")

    def _controls(self):
        if not hasattr(self,'start_button'):
            return
        locked = self.busy or self.import_worker is not None or self._closing
        for widget in (self.url, self.chrome, self.chrome_button, self.output, self.output_button, self.mode, self.video_url, self.entry, self.concurrency, self.muted, self.media, self.play, self.frame, self.complete, self.next_video, self.video_timeout, self.stall_timeout, self.import_button, self.template_button):
            widget.setEnabled(not locked)
        self.test_mode.setEnabled(not locked)
        self.background.setEnabled(not locked)
        self.flow_settings.setEnabled(not locked)
        self.start_button.setEnabled(self.backend_ready and not locked and bool(self._remaining() or (not self.batch_records and self.rejected)))
        same_batch=bool(self.batch_records) and self.batch_test_mode==self.test_mode.isChecked()
        self.start_button.setText("重试未完成身份" if same_batch else "启动测试" if self.test_mode.isChecked() else '启动登录验证')
        self.inspect_button.setEnabled(self.backend_ready and not locked)
        self.pause_button.setEnabled(self.busy and not self._closing)
        self.stop_button.setEnabled(self.busy and not self._closing)
        self.export_button.setEnabled(self.backend_ready and not locked and bool(self.result_folder))
        self.open_button.setEnabled(bool(self.result_folder))
        if not locked:
            self._video_controls()

    def _remaining(self):
        if not self.batch_records or self.batch_test_mode!=self.test_mode.isChecked():
            return self.candidates
        valid = {c.row for c in self.candidates}
        return [r.candidate for r in self.batch_records if r.status != "completed" and r.candidate.row in valid]

    def _ready(self):
        self.backend_ready = True
        self.show_status("就绪：关闭“启动测试”时仅验证登录并保留主页；开启后登录成功直接观看视频")
        self._controls()

    def _backend_finished(self):
        self.backend_ready = False
        self._controls()

    def show_status(self, text):
        text = redact(text)
        self.status.setText(text)
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")
        logging.getLogger("justvedio").info(text)

    def _choose_chrome(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择浏览器", "", "程序 (*.exe)")
        if path:
            self.chrome.setText(path)
    def _choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择结果目录", self.output.text())
        if path:
            self.output.setText(path)
    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入身份", "", "Excel (*.xlsx)")
        if path:
            self.import_file(path)
    def import_file(self, path):
        self.import_worker = ImportWorker(path, self)
        self.import_worker.result.connect(self.identities_loaded)
        self.import_worker.failed.connect(self.show_status)
        self.import_worker.finished.connect(self._import_finished)
        self.import_worker.start()
        self._controls()
    def _import_finished(self):
        self.import_worker.deleteLater()
        self.import_worker = None
        self._controls()
    def identities_loaded(self, result):
        self.candidates, self.rejected, self.batch_records = result.candidates, result.rejected, []
        self.batch_test_mode = None
        self.identity_summary.setText(f"工作表 {result.sheet} · 可用 {len(result.candidates)} 人 · 拒绝 {len(result.rejected)} 行")
        for issue in result.issues:
            self.show_status(issue)
        self._render()
        self._controls()
    def _save_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存空白身份表模板", "身份模板.xlsx", "Excel (*.xlsx)")
        if path:
            try:
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.append(["所在的区县", "姓名", "身份证号"])
                ws.column_dimensions['A'].width, ws.column_dimensions['B'].width, ws.column_dimensions['C'].width = 20, 18, 28
                for row in ws.iter_rows(min_row=2, max_row=1001, min_col=3, max_col=3):
                    row[0].number_format = '@'
                wb.save(path)
                wb.close()
                self.show_status("身份表模板已保存，身份证列已设为文本")
            except OSError:
                self.show_status("模板保存失败，请检查目标文件是否被占用")

    def _config(self):
        config = SiteConfig(self.url.text().strip(), self.chrome.text().strip())
        options = VideoOptions(concurrency=self.concurrency.value(), background=self.background.isChecked(), video_url=self.video_url.text().strip() if self.mode.currentData() == 'url' else '', entry_selector=self.entry.text().strip() if self.mode.currentData() == 'link' else '', video_selector=self.media.text().strip(), play_selector=self.play.text().strip(), frame_selector=self.frame.text().strip(), complete_selector=self.complete.text().strip(), next_selector=self.next_video.text().strip(), muted=self.muted.isChecked(), video_timeout_seconds=self.video_timeout.value()*60, stall_timeout_seconds=self.stall_timeout.value())
        return config, options
    def _start(self, kind):
        if self._check_expiry():
            return
        try:
            config, options = self._config()
            config.validate()
            options.validate_execution()
            if kind == 'watch' and self.test_mode.isChecked():
                options.validate(config)
                if self.mode.currentData() == 'link' and not options.entry_selector:
                    raise ValueError("请填写原网站内的视频入口选择器")
            if not self.output.text().strip():
                raise ValueError("请填写结果目录")
        except ValueError as error:
            self.show_status(str(error))
            return
        for key, value in {'url': config.url, 'chrome': config.chrome_path, 'output': self.output.text(), 'mode': self.mode.currentIndex(), 'video_url': self.video_url.text(), 'entry': self.entry.text(), 'concurrency': options.concurrency, 'background': options.background, 'muted': options.muted, 'media': options.video_selector, 'play': options.play_selector, 'frame': options.frame_selector, 'complete': options.complete_selector, 'next': options.next_selector, 'video_timeout': self.video_timeout.value(), 'stall_timeout': self.stall_timeout.value()}.items():
            self.settings.setValue(key, value)
        candidates = self._remaining() if kind == 'watch' else self.candidates
        rejected = self.rejected if kind=='watch' and (not self.batch_records or self.batch_test_mode!=self.test_mode.isChecked()) else ()
        self.busy = True
        self.pause_button.setText("暂停补位")
        self.backend.start_job(kind, config, candidates, self.output.text().strip(), rejected, options, test_mode=self.test_mode.isChecked())
        self._controls()
    def _pause(self):
        if self.backend.control.paused.is_set():
            self.backend.resume_queue()
            self.pause_button.setText("暂停补位")
            self.show_status("已恢复自动补位")
        else:
            self.backend.pause_queue()
            self.pause_button.setText("恢复补位")
            self.show_status("已暂停新身份补位；当前身份继续登录或观看")
        self._controls()
    def _stop(self):
        self.backend.pause_queue()
        box = QMessageBox(self)
        box.setWindowTitle("停止流程")
        box.setText("可等待当前所有身份完成登录及视频，或立即关闭当前会话。")
        graceful = box.addButton("当前全部完成后停止", QMessageBox.AcceptRole)
        immediate = box.addButton("立即停止", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == graceful:
            self.backend.stop_after_current()
            self.show_status("停止接入后续身份，等待当前所有身份完成")
        elif box.clickedButton() == immediate:
            self.backend.stop_job()
        elif self.pause_button.text() != "恢复补位":
            self.backend.resume_queue()
    def _finished(self):
        self.busy = False
        self.pause_button.setText("暂停补位")
        self._render()
        self._controls()
    def _batch_started(self, folder, records):
        self.result_folder, self.batch_records = folder, list(records)
        self.batch_test_mode=self.test_mode.isChecked()
        self.result_location.setText(folder)
        self._render()
    def _person_updated(self, record):
        if record.index < len(self.batch_records):
            previous = self.batch_records[record.index]
            self.batch_records[record.index] = record
            if previous.status == record.status:
                for key, table in self.tables.items():
                    row = getattr(self, '_table_rows', {}).get(key, {}).get(record.index)
                    if row is not None:
                        table.setItem(row, 5, QTableWidgetItem(f"{record.progress:.1f}%"))
                        table.setItem(row, 6, QTableWidgetItem(str(record.videos_completed)))
                        table.setItem(row, 7, QTableWidgetItem(record.reason))
                return
        self._render()
    def _render(self):
        from .batch import PersonResult
        records = self.batch_records or [PersonResult(i, c) for i, c in enumerate(self.candidates)]
        counts = {s: sum(r.status == s for r in records) for s in LABELS}
        self.counts.setText(f"总计 {len(records)} · 登录 {counts['running']} · 观看 {counts['watching']} · 完成 {counts['completed']} · 失败/中止 {counts['failed']+counts['stopped']} · 待接入 {counts['pending']} · 并发上限 {self.concurrency.value()}")
        self._table_rows = {}
        for key, table in self.tables.items():
            subset = [r for r in records if key == 'all' or (key == 'active' and r.status in ACTIVE_STATUSES) or (key == 'completed' and r.status == 'completed') or (key == 'failed' and r.status in {'failed','stopped'})]
            table.setRowCount(len(subset))
            self._table_rows[key] = {r.index: row for row, r in enumerate(subset)}
            for row, r in enumerate(subset):
                c = r.candidate
                for col, value in enumerate((str(c.row), c.district, c.name, c.masked_id, status_text(r), f"{r.progress:.1f}%", str(r.videos_completed), r.reason)):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, r.index)
                    item.setToolTip(value)
                    table.setItem(row, col, item)
    def _focus(self, table, row):
        item = table.item(row, 0)
        if item and self.backend_ready:
            self.backend.focus(item.data(Qt.UserRole))
    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self.expiry_timer.stop()
        if self.import_worker:
            self.import_worker.requestInterruption()
        self.backend.stop_job()
        self.backend.shutdown()
        self._controls()
        self.show_status("正在关闭本软件创建的浏览器并保存状态…")
        self.close_timer = QTimer(self)
        self.close_timer.timeout.connect(self._finish_close)
        self.close_timer.start(100)
    def _finish_close(self):
        if not self.backend.isRunning() and self.import_worker is None:
            self.close_timer.stop()
            self._allow_close = True
            self.close()
            QApplication.instance().quit()
