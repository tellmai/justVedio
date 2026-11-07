import logging
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QThread, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
    QApplication, QScrollArea)
from . import paths
from .controller import BrowserWorker
from .browsers import discover_browsers
from .models import DEFAULT_URL, SiteConfig, VideoOptions
from .importers import load_identities, load_identity_folder
from .privacy import redact
from .batch import LABELS, ACTIVE_STATUSES, build_records, status_text
from .version import APP_NAME, VERSION
from .settings import application_settings
from .expiry import is_expired
from .totals import load_completed_learning
from .daily import day_key, load_day
from .ui import ElidedLabel, MetricCard, PeopleTable, Switch, icon, stylesheet


class ImportWorker(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    def __init__(self, path, folder=False, parent=None):
        super().__init__(parent)
        self.path = path
        self.folder = folder
    def run(self):
        try:
            result = load_identity_folder(self.path) if self.folder else load_identities(self.path)
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
        self.batch_started_at = None
        self._expiry_handled = False
        self.learning_total = load_completed_learning()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        available = QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(min(820, available.width()), min(620, available.height()))
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
        self.backend.lifetime_updated.connect(self._lifetime_updated)
        self.backend.check_result.connect(lambda label, ok, detail: self.show_status(f"{label}：{'通过' if ok else '未通过'} · {detail}"))
        self.backend.finished.connect(self._backend_finished)
        self.backend.start()
        self._controls()
        self.expiry_timer=QTimer(self)
        self.expiry_timer.timeout.connect(self._check_expiry)
        self.expiry_timer.start(1000)
        QTimer.singleShot(150, self._load_startup_identities)

    def _check_expiry(self):
        if not is_expired():
            return False
        if not self._expiry_handled:
            self._expiry_handled = True
            self.expiry_timer.stop()
            self.hide()
            self.close()
        return True

    def _lifetime_updated(self, total):
        self.learning_total = max(0, int(total))
        self.lifetime_badge.setText(f'累计完成学习 {self.learning_total} 人次')

    def _build_ui(self):
        root = QWidget()
        root.setObjectName('workspace')
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(16)

        def label(text, name, wrap=False):
            result = QLabel(text)
            result.setObjectName(name)
            result.setWordWrap(wrap)
            return result

        def field(target, caption, control, hint=''):
            target.addWidget(label(caption, 'fieldLabel'))
            target.addWidget(control)
            if hint:
                target.addWidget(label(hint, 'fieldHint', True))
            target.addSpacing(8)

        def path_row(edit, button):
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            edit.setMinimumWidth(0)
            row.addWidget(edit, 1)
            row.addWidget(button)
            return container

        def page():
            content = QWidget()
            body = QVBoxLayout(content)
            body.setContentsMargins(0, 16, 8, 6)
            body.setSpacing(8)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(content)
            return content, body, scroll

        header = QHBoxLayout()
        header.setSpacing(13)
        mark = QLabel()
        mark.setFixedSize(46, 46)
        mark.setPixmap(icon('brand', size=46).pixmap(46, 46))
        header.addWidget(mark)
        brand = QVBoxLayout()
        brand.setSpacing(1)
        brand_line = QHBoxLayout()
        brand_line.setSpacing(10)
        brand_line.addWidget(label(APP_NAME, 'brandTitle'))
        brand_line.addWidget(label(f'v{VERSION}', 'versionBadge'), 0, Qt.AlignVCenter)
        brand_line.addStretch()
        brand.addLayout(brand_line)
        brand.addWidget(label('视频任务工作台  /  登录 · 观看 · 自动补位', 'brandSubtitle'))
        header.addLayout(brand, 1)
        system = QVBoxLayout()
        system.setSpacing(5)
        self.run_badge = label('●  正在初始化', 'runBadge')
        system.addWidget(self.run_badge, 0, Qt.AlignRight)
        self.lifetime_badge = label(f'累计完成学习 {self.learning_total} 人次', 'lifetimeBadge')
        self.lifetime_badge.setToolTip('历次学习完成累加；同一人每次完成学习都会计入')
        system.addWidget(self.lifetime_badge, 0, Qt.AlignRight)
        header.addLayout(system)
        layout.addLayout(header)

        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(16)
        layout.addWidget(self.workspace_splitter, 1)
        config = QFrame()
        config.setObjectName('configPanel')
        config.setMinimumWidth(276)
        config.setMaximumWidth(380)
        config_layout = QVBoxLayout(config)
        config_layout.setContentsMargins(18, 18, 10, 14)
        config_layout.setSpacing(7)
        config_layout.addWidget(label('运行配置', 'panelTitle'))
        config_layout.addWidget(label('确认流程后，即可启动本次任务', 'panelCaption'))
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName('configTabs')
        self.settings_tabs.setDocumentMode(True)
        config_layout.addWidget(self.settings_tabs, 1)

        execution, execution_layout, self.settings_scroll = page()
        option = QFrame()
        option.setObjectName('modeOption')
        option_layout = QVBoxLayout(option)
        option_layout.setContentsMargins(12, 9, 12, 12)
        option_layout.setSpacing(3)
        option_layout.addWidget(label('视频学习', 'stepTitle'))
        option_layout.addWidget(label('登录后自动进入旁听学习、播放至结束并确认。', 'modeDescription', True))
        execution_layout.addWidget(option)
        execution_layout.addSpacing(10)
        divider = QFrame()
        divider.setObjectName('divider')
        divider.setFixedHeight(1)
        execution_layout.addWidget(divider)
        execution_layout.addSpacing(6)
        self.background = Switch('后台执行（隐藏浏览器）')
        self.background.setObjectName('backgroundExecution')
        self.background.setChecked(self.settings.value('background', True, type=bool))
        self.background.setToolTip('仅隐藏本批次浏览器，主界面继续显示进度、日志及暂停/停止操作。取消勾选后可观察浏览器；设置在批次启动时生效。')
        self.background.toggled.connect(self._controls)
        execution_layout.addWidget(self.background)
        execution_layout.addWidget(label('主界面保持可见，可随时暂停或停止。', 'fieldHint', True))
        execution_layout.addSpacing(10)
        browser_card = QFrame()
        browser_card.setObjectName('browserCard')
        browser_layout = QVBoxLayout(browser_card)
        browser_layout.setContentsMargins(12, 10, 12, 12)
        browser_layout.setSpacing(6)
        browser_head = QHBoxLayout()
        browser_head.setSpacing(6)
        browser_head.addWidget(label('浏览器', 'fieldLabel'))
        browser_head.addStretch()
        self.browser_count = label('', 'fieldHint')
        browser_head.addWidget(self.browser_count)
        browser_layout.addLayout(browser_head)
        self.browser_list = QVBoxLayout()
        self.browser_list.setSpacing(2)
        browser_layout.addLayout(self.browser_list)
        browser_actions = QHBoxLayout()
        browser_actions.setSpacing(4)
        self.browser_refresh = QPushButton('刷新')
        self.browser_refresh.setProperty('role', 'quiet')
        self.browser_refresh.setToolTip('重新检测本机可用浏览器')
        self.browser_refresh.clicked.connect(self._load_browsers)
        self.browser_select_all = QPushButton('全选')
        self.browser_select_all.setProperty('role', 'quiet')
        self.browser_select_all.setToolTip('勾选全部可用浏览器；身份按勾选顺序轮流分配')
        self.browser_select_all.clicked.connect(self._toggle_all_browsers)
        browser_actions.addWidget(self.browser_refresh)
        browser_actions.addWidget(self.browser_select_all)
        browser_actions.addStretch()
        browser_layout.addLayout(browser_actions)
        browser_layout.addWidget(label('每人一个新浏览器；学完后关闭浏览器并自动接同类型的下一位。', 'fieldHint', True))
        execution_layout.addWidget(browser_card)
        execution_layout.addSpacing(12)
        workflow = QFrame()
        workflow.setObjectName('workflowCard')
        workflow_layout = QVBoxLayout(workflow)
        workflow_layout.setContentsMargins(12, 12, 12, 14)
        workflow_layout.setSpacing(14)
        workflow_layout.addWidget(label('本次执行流程', 'fieldHint'))
        self.workflow_labels = []
        for number, title, note in ((1, '身份登录', '独立浏览器 · 自动识别验证码'),
                                    (2, '旁听学习', '点击开始/继续旁听学习并播放'),
                                    (3, '完成并记录', '确认后关闭浏览器，自动补位')):
            step = QHBoxLayout()
            step.setSpacing(10)
            number_label = label(str(number).zfill(2), 'stepNumber')
            number_label.setAlignment(Qt.AlignCenter)
            number_label.setFixedSize(22, 22)
            step.addWidget(number_label, 0, Qt.AlignTop)
            copy = QVBoxLayout()
            copy.setSpacing(3)
            step_title = label(title, 'stepTitle')
            step_note = label(note, 'stepNote', True)
            copy.addWidget(step_title)
            copy.addWidget(step_note)
            self.workflow_labels.append((step_title, step_note))
            step.addLayout(copy, 1)
            workflow_layout.addLayout(step)
        execution_layout.addWidget(workflow)
        execution_layout.addStretch()
        execution_layout.addWidget(label('运行中配置将锁定，批次结束后恢复编辑。', 'fieldHint', True))
        self.settings_tabs.addTab(self.settings_scroll, '执行')

        self.flow_settings, video_layout, video_scroll = page()
        defaults = VideoOptions()
        self.learning_entry = QLineEdit(self.settings.value('learning_entry', defaults.learning_entry_text))
        self.learning_entry.setPlaceholderText('开始旁听学习|继续旁听学习')
        field(video_layout, '学习入口文字', self.learning_entry, '登录后按文字查找入口；找不到即把该身份记为失败。')
        self.play = QLineEdit(self.settings.value('play', ''))
        self.play.setPlaceholderText('留空时自动点击视频中间的播放按钮')
        field(video_layout, '播放按钮选择器', self.play)
        self.confirm = QLineEdit(self.settings.value('confirm', defaults.confirm_text))
        self.confirm.setPlaceholderText('确认完成学习|完成学习|确认完成')
        field(video_layout, '完成确认文字', self.confirm, '视频结束后如出现该按钮会自动点击；没有则不点击。')
        self.home_text = QLineEdit(self.settings.value('home', defaults.home_text))
        self.home_text.setPlaceholderText('返回考生主页|返回主页')
        field(video_layout, '返回主页文字', self.home_text, '确认完成后返回考生主页，再关闭浏览器。')
        self.media = QLineEdit(self.settings.value('media', defaults.video_selector))
        field(video_layout, '视频元素', self.media)
        self.frame = QLineEdit(self.settings.value('frame', ''))
        self.frame.setPlaceholderText('可选')
        field(video_layout, '视频 iframe', self.frame)
        self.video_timeout = QSpinBox()
        self.video_timeout.setRange(1, 720)
        self.video_timeout.setValue(int(self.settings.value('video_timeout', 120)))
        self.video_timeout.setSuffix(' 分钟')
        field(video_layout, '最长等待', self.video_timeout, '视频正常播放后不再操作浏览器，直到播放结束。')
        video_layout.addStretch()
        video_layout.addWidget(label('确认完成并返回主页后立即关闭浏览器，再接入下一位。', 'fieldHint', True))
        self.settings_tabs.addTab(video_scroll, '学习')

        connection, connection_layout, connection_scroll = page()
        self.url = QLineEdit(self.settings.value('url', DEFAULT_URL))
        field(connection_layout, '登录入口', self.url)
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
        self.output = QLineEdit(self.settings.value('output', str(base / 'results')))
        self.output_button = QPushButton('浏览…')
        self.output_button.setToolTip('选择结果目录')
        self.output_button.clicked.connect(self._choose_output)
        field(connection_layout, '结果目录', path_row(self.output, self.output_button), '每个批次独立保存统计文件，可重新导出。')
        connection_layout.addStretch()
        connection_layout.addWidget(label('每个身份使用独立浏览器与独立配置文件，互不影响。', 'fieldHint', True))
        connection_layout.addWidget(label(f'启动时自动加载 {paths.identities_folder()} 下的所有 .xlsx；学习完成与失败记录分别写入 {paths.completed_folder()} 和 {paths.failed_folder()}。', 'fieldHint', True))
        self.settings_tabs.addTab(connection_scroll, '连接')
        self.inspect_button = QPushButton('环境检测')
        self.inspect_button.setIcon(icon('monitor'))
        self.inspect_button.clicked.connect(lambda: self._start('inspect'))
        config_layout.addSpacing(5)
        config_layout.addWidget(self.inspect_button)
        self.workspace_splitter.addWidget(config)

        dashboard = QWidget()
        dashboard.setMinimumWidth(450)
        dashboard_layout = QVBoxLayout(dashboard)
        dashboard_layout.setContentsMargins(0, 0, 0, 0)
        dashboard_layout.setSpacing(14)
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.metrics = {}
        for key, title, mark, tone, note in (
            ('total', '已导入', 'people', 'neutral', '等待导入'),
            ('active', '进行中', 'play', 'blue', '登录与观看'),
            ('completed', '已完成', 'check', 'teal', '完成率 0%'),
            ('failed', '需关注', 'alert', 'amber', '失败或中止')):
            card = MetricCard(title, mark, tone, note)
            self.metrics[key] = card
            metrics.addWidget(card, 1)
        dashboard_layout.addLayout(metrics)

        people = QFrame()
        people.setObjectName('peoplePanel')
        people_layout = QVBoxLayout(people)
        people_layout.setContentsMargins(16, 14, 16, 12)
        people_layout.setSpacing(10)
        people_header = QHBoxLayout()
        people_header.setSpacing(8)
        people_heading = QVBoxLayout()
        people_heading.setSpacing(4)
        people_heading.addWidget(label('人员任务', 'panelTitle'))
        self.identity_summary = ElidedLabel('导入身份表，开始新的批次')
        self.identity_summary.setObjectName('identitySummary')
        people_heading.addWidget(self.identity_summary)
        people_header.addLayout(people_heading, 1)
        self.import_button = QPushButton("导入身份 Excel")
        self.import_button.setObjectName('importIdentities')
        self.import_button.setIcon(icon('upload', '#137E74', 18))
        self.import_button.setShortcut('Ctrl+O')
        self.import_button.setToolTip('导入身份 Excel（Ctrl+O）')
        self.import_button.clicked.connect(self._choose_file)
        self.template_button = QPushButton('保存模板')
        self.template_button.setProperty('role', 'quiet')
        self.template_button.setIcon(icon('file', size=18))
        self.template_button.setToolTip('保存空白身份表模板，身份证列已设为文本')
        self.template_button.clicked.connect(self._save_template)
        people_header.addWidget(self.template_button)
        people_header.addWidget(self.import_button)
        people_layout.addLayout(people_header)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('peopleTabs')
        self.tabs.setDocumentMode(True)
        self.tabs.setMinimumHeight(104)
        self.tables = {}
        for key, caption, empty_title, empty_note in (
            ('all', '全部身份', '等待导入身份', '导入 Excel 身份表，即可开始登录或视频流程。'),
            ('active', '进行中', '暂无正在执行的身份', '启动任务后，登录与观看进度会显示在这里。'),
            ('completed', '已完成', '暂无已完成的身份', '完成所选流程的身份会自动归入此处。'),
            ('failed', '失败 / 中止', '暂无失败或中止的身份', '异常记录会集中显示，方便查看原因并重试。')):
            table = PeopleTable(empty_title, empty_note)
            table.setHorizontalHeaderLabels(['行号', '区县', '姓名', '身份证号（脱敏）', '浏览器', '状态', '步骤进度', '视频数', '结果 / 原因'])
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.setShowGrid(False)
            table.setWordWrap(False)
            table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            table.setMouseTracking(True)
            heading = table.horizontalHeader()
            heading.setSectionResizeMode(QHeaderView.Interactive)
            heading.setMinimumSectionSize(38)
            heading.setStretchLastSection(True)
            for column, width in enumerate((44, 62, 86, 136, 92, 100, 98, 56, 150)):
                table.setColumnWidth(column, width)
            table.verticalHeader().setDefaultSectionSize(40)
            table.verticalHeader().hide()
            table.cellDoubleClicked.connect(lambda row, col, t=table: self._focus(t, row))
            self.tables[key] = table
            self.tabs.addTab(table, caption)
        people_layout.addWidget(self.tabs, 1)
        progress_row = QHBoxLayout()
        self.counts = label('等待导入', 'queueCaption')
        progress_row.addWidget(self.counts, 1)
        self.progress_caption = label('已完成 0 / 0', 'progressCaption')
        progress_row.addWidget(self.progress_caption)
        self.batch_progress = QProgressBar()
        self.batch_progress.setTextVisible(False)
        self.batch_progress.setRange(0, 100)
        self.batch_progress.setValue(0)
        self.batch_progress.setFixedWidth(76)
        progress_row.addWidget(self.batch_progress)
        people_layout.addLayout(progress_row)
        result_strip = QFrame()
        result_strip.setObjectName('resultStrip')
        result_row = QHBoxLayout(result_strip)
        result_row.setContentsMargins(10, 6, 4, 6)
        result_row.setSpacing(6)
        folder = QLabel()
        folder.setPixmap(icon('folder', '#8A9BA6', 17).pixmap(17, 17))
        result_row.addWidget(folder)
        self.result_location = ElidedLabel('批次结束后，可打开结果目录查看统计文件')
        self.result_location.setObjectName('resultPath')
        result_row.addWidget(self.result_location, 1)
        self.export_button = QPushButton('重新导出')
        self.export_button.setProperty('role', 'quiet')
        self.export_button.clicked.connect(lambda: self._start('export'))
        self.open_button = QPushButton('打开结果目录')
        self.open_button.setProperty('role', 'quiet')
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.result_folder)))
        result_row.addWidget(self.export_button)
        result_row.addWidget(self.open_button)
        people_layout.addWidget(result_strip)
        dashboard_layout.addWidget(people, 1)

        log_panel = QFrame()
        log_panel.setObjectName('logPanel')
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(14, 7, 10, 7)
        log_layout.setSpacing(6)
        log_header = QHBoxLayout()
        log_header.setSpacing(8)
        log_icon = QLabel()
        log_icon.setPixmap(icon('log', '#6E8792', 18).pixmap(18, 18))
        log_header.addWidget(log_icon)
        log_header.addWidget(label('运行日志', 'logTitle'))
        self.status = ElidedLabel('正在初始化浏览器控制模块…')
        self.status.setObjectName('liveStatus')
        log_header.addWidget(self.status, 1)
        self.log_toggle = QToolButton()
        self.log_toggle.setCheckable(True)
        self.log_toggle.setText('展开')
        self.log_toggle.setArrowType(Qt.DownArrow)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.log_toggle.setShortcut('Ctrl+L')
        self.log_toggle.setToolTip('展开 / 收起运行日志（Ctrl+L）')
        log_header.addWidget(self.log_toggle)
        log_layout.addLayout(log_header)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setFixedHeight(92)
        self.log.hide()
        self.log_toggle.toggled.connect(self._toggle_log)
        log_layout.addWidget(self.log)
        dashboard_layout.addWidget(log_panel)
        self.workspace_splitter.addWidget(dashboard)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([306, 814])

        command = QFrame()
        command.setObjectName('commandBar')
        command_layout = QHBoxLayout(command)
        command_layout.setContentsMargins(18, 12, 14, 12)
        command_layout.setSpacing(18)
        command_copy = QVBoxLayout()
        command_copy.setSpacing(5)
        self.command_title = label('登录验证模式', 'commandTitle')
        self.command_note = ElidedLabel()
        self.command_note.setObjectName('commandNote')
        command_copy.addWidget(self.command_title)
        command_copy.addWidget(self.command_note)
        command_layout.addLayout(command_copy, 1)
        row = self.action_bar = QHBoxLayout()
        row.setSpacing(8)
        self.pause_button = QPushButton("暂停补位")
        self.pause_button.setIcon(icon('pause', size=16))
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName('stopFlow')
        self.stop_button.setIcon(icon('stop', '#AD6262', 16))
        self.start_button = QPushButton('启动视频学习')
        self.start_button.setObjectName('startWatch')
        self.start_button.setIcon(icon('play', '#FFFFFF', 16))
        self.start_button.setMinimumWidth(160)
        self.start_button.clicked.connect(lambda: self._start('watch'))
        self.pause_button.clicked.connect(self._pause)
        self.stop_button.clicked.connect(self._stop)
        for button in (self.pause_button, self.stop_button, self.start_button):
            row.addWidget(button)
        command_layout.addLayout(row)
        layout.addWidget(command)
        for button in self.findChildren(QPushButton) + self.findChildren(QToolButton):
            button.setCursor(Qt.PointingHandCursor)
        for edit in (self.url, self.output, self.learning_entry, self.play, self.confirm, self.home_text, self.media, self.frame):
            edit.setToolTip(edit.text())
            edit.textChanged.connect(edit.setToolTip)
        self.identity_summary.setText(f'启动时自动加载 {paths.identities_folder()}，或按 Ctrl+O 导入')
        self.identity_summary.setToolTip(str(paths.identities_folder()))
        self.setStyleSheet(stylesheet())
        self._load_browsers()
        self._render()

    def _load_browsers(self, *_):
        """Detect installed browsers and restore the saved selection."""
        saved = self.settings.value('browsers', [])
        if isinstance(saved, str):
            saved = [saved]
        saved = [str(path).casefold() for path in saved if path]
        previous = [path for path, box in getattr(self, 'browser_boxes', {}).items() if box.isChecked()]
        # A refresh keeps exactly what is checked now; the first build restores
        # the saved preference instead.
        wanted = [path.casefold() for path in previous] if hasattr(self, 'browser_boxes') else saved
        try:
            self.browser_choices = discover_browsers()
        except Exception:
            self.browser_choices = []
        while self.browser_list.count():
            item = self.browser_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.browser_boxes = {}
        for index, choice in enumerate(self.browser_choices):
            box = QCheckBox(choice.name)
            box.setToolTip(choice.path)
            box.setChecked(choice.path.casefold() in wanted if wanted else index == 0)
            box.toggled.connect(self._browser_selection_changed)
            self.browser_list.addWidget(box)
            self.browser_boxes[choice.path] = box
        if self.browser_choices and not any(box.isChecked() for box in self.browser_boxes.values()):
            self.browser_boxes[self.browser_choices[0].path].setChecked(True)
        self._browser_selection_changed()

    def _selected_browsers(self):
        boxes = getattr(self, 'browser_boxes', {})
        return [choice for choice in getattr(self, 'browser_choices', []) if choice.path in boxes and boxes[choice.path].isChecked()]

    def _browser_selection_changed(self, *_):
        selected = self._selected_browsers()
        if hasattr(self, 'browser_count'):
            self.browser_count.setText(f"已选 {len(selected)} / {len(getattr(self, 'browser_choices', []))}")
        if hasattr(self, 'start_button'):
            self._controls()

    def _toggle_all_browsers(self, *_):
        boxes = list(getattr(self, 'browser_boxes', {}).values())
        target = not all(box.isChecked() for box in boxes)
        for box in boxes:
            box.blockSignals(True)
            box.setChecked(target)
            box.blockSignals(False)
        self._browser_selection_changed()

    def _toggle_log(self, expanded):
        self.log.setVisible(expanded)
        self.log_toggle.setText('收起' if expanded else '展开')
        self.log_toggle.setArrowType(Qt.UpArrow if expanded else Qt.DownArrow)

    def _controls(self):
        if not hasattr(self,'start_button'):
            return
        locked = self.busy or self.import_worker is not None or self._closing
        for widget in (self.url, self.output, self.output_button, self.media, self.play, self.frame,
                       self.learning_entry, self.confirm, self.home_text, self.video_timeout,
                       self.import_button, self.template_button,
                       self.browser_refresh, self.browser_select_all):
            widget.setEnabled(not locked)
        for box in getattr(self, 'browser_boxes', {}).values():
            box.setEnabled(not locked)
        self.background.setEnabled(not locked)
        self.flow_settings.setEnabled(not locked)
        self.start_button.setEnabled(self.backend_ready and not locked and bool(self._selected_browsers()) and bool(self._remaining()))
        same_batch=bool(self.batch_records)
        has_failed = any(r.status in {'failed', 'stopped'} for r in self.batch_records)
        has_completed = any(r.status == 'completed' for r in self.batch_records)
        if self.busy:
            self.start_button.setText('正在执行…')
        elif same_batch and not self._remaining():
            self.start_button.setText('本日学习已完成' if all(r.status == 'completed' for r in self.batch_records) else '无待学习身份')
        elif same_batch and has_failed:
            self.start_button.setText('重试未完成身份')
        elif same_batch and has_completed:
            self.start_button.setText('继续本日学习')
        else:
            self.start_button.setText('启动视频学习')
        self.inspect_button.setEnabled(self.backend_ready and not locked)
        self.pause_button.setEnabled(self.busy and not self._closing)
        self.stop_button.setEnabled(self.busy and not self._closing)
        self.export_button.setEnabled(self.backend_ready and not locked and bool(self.result_folder))
        self.open_button.setEnabled(bool(self.result_folder))
        self._sync_presentation()

    def _sync_presentation(self):
        execution = '后台执行' if self.background.isChecked() else '显示浏览器'
        self.command_title.setText(f'视频学习模式 · {execution}')
        self.command_note.setText('身份登录 → 旁听学习 → 播放结束 → 确认并关闭浏览器 → 自动补位')
        if self._closing:
            text, tone = '正在关闭', 'neutral'
        elif self.import_worker is not None:
            text, tone = '正在导入', 'neutral'
        elif not self.backend_ready:
            text, tone = '正在初始化', 'neutral'
        elif self.busy:
            paused = self.backend.control.paused.is_set()
            text, tone = ('已暂停补位', 'amber') if paused else ('任务执行中', 'teal')
        elif self.batch_records and any(r.status in {'failed', 'stopped'} for r in self.batch_records):
            text, tone = '有未完成身份', 'amber'
        elif self.batch_records and all(r.status == 'completed' for r in self.batch_records):
            text, tone = '批次已完成', 'teal'
        else:
            text, tone = '系统就绪', 'teal'
        self.run_badge.setText('●  ' + text)
        if self.run_badge.property('tone') != tone:
            self.run_badge.setProperty('tone', tone)
            self.run_badge.style().unpolish(self.run_badge)
            self.run_badge.style().polish(self.run_badge)

    def _remaining(self):
        if not self.batch_records:
            return self.candidates
        valid = {c.id_number for c in self.candidates}
        return [r.candidate for r in self.batch_records if r.status != "completed" and r.candidate.id_number in valid]

    def _ready(self):
        self.backend_ready = True
        self.show_status("就绪：点击“启动视频学习”后按已勾选浏览器并发登录、旁听学习并自动补位")
        self._controls()

    def _backend_finished(self):
        self.backend_ready = False
        self._controls()

    def show_status(self, text):
        text = redact(text)
        self.status.setText(text)
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")
        logging.getLogger("justvedio").info(text)

    def _choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择结果目录", self.output.text())
        if path:
            self.output.setText(path)
    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入身份", "", "Excel (*.xlsx)")
        if path:
            self.import_file(path)
    def import_file(self, path):
        self._start_import(path, False)
    def _import_finished(self):
        self.import_worker.deleteLater()
        self.import_worker = None
        self._controls()
    def identities_loaded(self, result):
        self.candidates, self.rejected = result.candidates, result.rejected
        try:
            prior = load_day(day_key())
        except Exception:
            prior = {}
        self.batch_records = build_records(result.candidates, result.rejected, prior)
        completed = sum(record.status == 'completed' for record in self.batch_records)
        summary = f"{result.sheet} · 可用 {len(result.candidates)} 人"
        if completed:
            summary += f" · 本日已完成 {completed} 人"
        summary += f" · 拒绝 {len(result.rejected)} 行"
        self.identity_summary.setText(summary)
        self.identity_summary.setToolTip(summary)
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
        config = SiteConfig(self.url.text().strip())
        options = VideoOptions(background=self.background.isChecked(),
                               learning_entry_text=self.learning_entry.text().strip(),
                               video_selector=self.media.text().strip(),
                               play_selector=self.play.text().strip(),
                               frame_selector=self.frame.text().strip(),
                               confirm_text=self.confirm.text().strip(),
                               home_text=self.home_text.text().strip(),
                               video_timeout_seconds=self.video_timeout.value()*60)
        return config, options
    def _start(self, kind):
        if self._check_expiry():
            return
        selected = self._selected_browsers()
        try:
            config, options = self._config()
            config.validate()
            options.validate_execution()
            if kind == 'watch' and not selected:
                raise ValueError("请至少勾选一个浏览器")
            if kind == 'watch':
                for value, label in ((options.learning_entry_text, '学习入口文字'), (options.confirm_text, '完成确认文字'),
                                     (options.home_text, '返回主页文字'), (options.video_selector, '视频元素')):
                    if not value:
                        raise ValueError(f"{label}不能为空")
            if not self.output.text().strip():
                raise ValueError("请填写结果目录")
        except ValueError as error:
            self.show_status(str(error))
            return
        for key, value in {'url': config.url, 'output': self.output.text(), 'background': options.background,
                           'learning_entry': options.learning_entry_text, 'media': options.video_selector,
                           'play': options.play_selector, 'frame': options.frame_selector,
                           'confirm': options.confirm_text, 'home': options.home_text,
                           'video_timeout': self.video_timeout.value()}.items():
            self.settings.setValue(key, value)
        if kind == 'watch':
            self.settings.setValue('browsers', [choice.path for choice in selected])
        # Pass the whole daily roster; completed people are seeded from the
        # daily ledger and skipped, failed people become pending for a retry.
        candidates = self.candidates
        rejected = self.rejected if kind == 'watch' else ()
        self.batch_started_at = datetime.now()
        self.busy = True
        self.pause_button.setText("暂停补位")
        self.backend.start_job(kind, config, candidates, self.output.text().strip(), rejected, options,
                               browsers=selected if kind == 'watch' else (),
                               started_at=self.batch_started_at)
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
        box.setText("可等待当前所有身份完成，或立即停止。停止后不会关闭已经打开的浏览器。")
        graceful = box.addButton("当前全部完成后停止", QMessageBox.AcceptRole)
        immediate = box.addButton("立即停止", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == graceful:
            self.backend.stop_after_current()
            self.show_status("停止接入后续身份，等待当前所有身份完成；已打开的浏览器将保留")
        elif box.clickedButton() == immediate:
            self.backend.stop_job()
            self.show_status("已请求立即停止；已打开的浏览器将保留")
        elif self.pause_button.text() != "恢复补位":
            self.backend.resume_queue()
    def _finished(self):
        self.busy = False
        self.pause_button.setText("暂停补位")
        self._render()
        self._controls()
    def _batch_started(self, folder, records):
        self.result_folder, self.batch_records = folder, list(records)
        self.result_location.setText(folder)
        self._render()
    def _load_startup_identities(self):
        folder = paths.identities_folder()
        if not folder.is_dir():
            return
        if not any(folder.glob('*.xlsx')):
            self.show_status(f"未发现身份表：把 .xlsx 放入 {folder}，或按 Ctrl+O 导入")
            return
        if self.candidates or self.batch_records:
            return
        self.import_folder(str(folder))
    def import_folder(self, path):
        self._start_import(path, True)
    def _start_import(self, path, folder):
        self.import_worker = ImportWorker(path, folder, self)
        self.import_worker.result.connect(self.identities_loaded)
        self.import_worker.failed.connect(self.show_status)
        self.import_worker.finished.connect(self._import_finished)
        self.import_worker.start()
        self._controls()
    def _person_updated(self, record):
        if record.index < len(self.batch_records):
            previous = self.batch_records[record.index]
            self.batch_records[record.index] = record
            if previous.status == record.status:
                for key, table in self.tables.items():
                    row = getattr(self, '_table_rows', {}).get(key, {}).get(record.index)
                    if row is not None:
                        for col, value in ((6, f'{record.progress:.1f}%'), (7, str(record.videos_completed)), (8, record.reason)):
                            table.setItem(row, col, self._table_item(value, record, col))
                return
        self._render()

    @staticmethod
    def _table_item(value, record, column):
        item = QTableWidgetItem(value)
        item.setData(Qt.UserRole, record.index)
        item.setData(Qt.UserRole + 1, record.status)
        item.setToolTip(value)
        if column in (0, 7):
            item.setTextAlignment(Qt.AlignCenter)
        return item

    def _render(self):
        from .batch import PersonResult
        records = self.batch_records or [PersonResult(i, c) for i, c in enumerate(self.candidates)]
        counts = {s: sum(r.status == s for r in records) for s in LABELS}
        total = len(records)
        completed = counts['completed']
        percent = round(completed / total * 100) if total else 0
        values = {'total': total, 'active': counts['running'] + counts['watching'],
                  'completed': completed, 'failed': counts['failed'] + counts['stopped']}
        notes = {'total': f"待接入 {counts['pending']} 人", 'active': f"登录 {counts['running']} · 观看 {counts['watching']}",
                 'completed': f'完成率 {percent}%', 'failed': f"失败 {counts['failed']} · 中止 {counts['stopped']}"}
        for key, card in self.metrics.items():
            card.value.setText(str(values[key]))
            card.note.setText(notes[key])
        self.counts.setText(f"待接入 {counts['pending']} 人 · 并发 {len(self._selected_browsers())} 路" if records else '导入后可查看各身份的实时进度')
        self.progress_caption.setText(f'已完成 {completed} / {total}')
        self.batch_progress.setValue(percent)
        self.batch_progress.setToolTip(f'已完成 {completed} 人，共 {total} 人（{percent}%）')
        self._table_rows = {}
        captions = {'all': '全部身份', 'active': '进行中', 'completed': '已完成', 'failed': '失败 / 中止'}
        for tab_index, (key, table) in enumerate(self.tables.items()):
            subset = [r for r in records if key == 'all' or (key == 'active' and r.status in ACTIVE_STATUSES) or (key == 'completed' and r.status == 'completed') or (key == 'failed' and r.status in {'failed','stopped'})]
            self.tabs.setTabText(tab_index, f'{captions[key]}  {len(subset)}')
            selected = table.item(table.currentRow(), 0)
            selected_index = selected.data(Qt.UserRole) if selected else None
            vertical, horizontal = table.verticalScrollBar().value(), table.horizontalScrollBar().value()
            table.setUpdatesEnabled(False)
            try:
                table.setRowCount(len(subset))
                self._table_rows[key] = {r.index: row for row, r in enumerate(subset)}
                for row, r in enumerate(subset):
                    c = r.candidate
                    for col, value in enumerate((str(c.row), c.district, c.name, c.masked_id, r.browser, status_text(r), f'{r.progress:.1f}%', str(r.videos_completed), r.reason)):
                        table.setItem(row, col, self._table_item(value, r, col))
                if selected_index in self._table_rows[key]:
                    table.selectRow(self._table_rows[key][selected_index])
                table.verticalScrollBar().setValue(vertical)
                table.horizontalScrollBar().setValue(horizontal)
            finally:
                table.setUpdatesEnabled(True)
        if hasattr(self, 'command_title'):
            self._sync_presentation()
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
        self.backend.begin_shutdown()
        self._controls()
        self.show_status("正在退出；已打开的浏览器保持运行，不会随软件关闭")
        self.close_timer = QTimer(self)
        self.close_timer.timeout.connect(self._finish_close)
        self.close_timer.start(100)
    def _finish_close(self):
        if not self.backend.isRunning() and self.import_worker is None:
            self.close_timer.stop()
            self._allow_close = True
            self.close()
            QApplication.instance().quit()
