"""Shared presentation components for the desktop workspace."""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QVBoxLayout,
)


COLORS = {
    "neutral": ("#536775", "#EFF3F5"),
    "teal": ("#137E74", "#E7F4F0"),
    "blue": ("#3775B1", "#EAF2FB"),
    "amber": ("#AD6A25", "#FFF4E5"),
    "red": ("#B64C50", "#FBEDEE"),
}
STATUS_TONES = {
    "pending": "neutral", "running": "blue", "watching": "teal",
    "completed": "teal", "failed": "red", "stopped": "amber",
}


def icon(name, color="#617684", size=24):
    """Small vector marks, rendered at the current screen's pixel density."""
    from PySide6.QtWidgets import QApplication
    screen = QApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 24, size / 24)
    painter.setPen(QPen(QColor(color), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    if name == "brand":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#137E74"))
        painter.drawRoundedRect(QRectF(0, 0, 24, 24), 7, 7)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPolygon(QPolygonF([QPointF(9, 6.8), QPointF(9, 17.2), QPointF(17.2, 12)]))
    elif name == "people":
        painter.drawEllipse(QRectF(8, 3.5, 8, 8))
        painter.drawArc(QRectF(4, 13, 16, 14), 0, 180 * 16)
        painter.drawArc(QRectF(15, 5, 6, 7), -70 * 16, 150 * 16)
        painter.drawArc(QRectF(15, 14, 8, 9), 0, 90 * 16)
    elif name == "play":
        painter.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(8, 19), QPointF(19, 12)]))
    elif name == "check":
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawPolyline(QPolygonF([QPointF(7.5, 12), QPointF(10.5, 15), QPointF(16.5, 9)]))
    elif name == "alert":
        painter.drawRoundedRect(QRectF(3, 3, 18, 18), 6, 6)
        painter.drawLine(QPointF(12, 7), QPointF(12, 12))
        painter.drawPoint(QPointF(12, 16.5))
    elif name == "upload":
        painter.drawPolyline(QPolygonF([QPointF(4, 15), QPointF(4, 20), QPointF(20, 20), QPointF(20, 15)]))
        painter.drawLine(QPointF(12, 4), QPointF(12, 15))
        painter.drawPolyline(QPolygonF([QPointF(7.5, 8.5), QPointF(12, 4), QPointF(16.5, 8.5)]))
    elif name == "file":
        path = QPainterPath(QPointF(6, 3))
        for point in ((14, 3), (19, 8), (19, 21), (6, 21), (6, 3)):
            path.lineTo(*point)
        painter.drawPath(path)
        painter.drawPolyline(QPolygonF([QPointF(14, 3), QPointF(14, 8), QPointF(19, 8)]))
        painter.drawLine(QPointF(9, 12), QPointF(15, 12))
        painter.drawLine(QPointF(9, 16), QPointF(15, 16))
    elif name == "folder":
        path = QPainterPath(QPointF(3, 7))
        for point in ((3, 5), (9, 5), (11, 7), (21, 7), (21, 20), (3, 20), (3, 7)):
            path.lineTo(*point)
        painter.drawPath(path)
    elif name == "pause":
        painter.drawLine(QPointF(8, 5), QPointF(8, 19))
        painter.drawLine(QPointF(16, 5), QPointF(16, 19))
    elif name == "stop":
        painter.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    elif name == "monitor":
        painter.drawRoundedRect(QRectF(3, 4, 18, 13), 2, 2)
        painter.drawLine(QPointF(12, 17), QPointF(12, 21))
        painter.drawLine(QPointF(8, 21), QPointF(16, 21))
        painter.drawPolyline(QPolygonF([QPointF(7, 11), QPointF(10, 13), QPointF(16, 8)]))
    elif name == "log":
        painter.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        painter.drawPolyline(QPolygonF([QPointF(7, 9), QPointF(10, 12), QPointF(7, 15)]))
        painter.drawLine(QPointF(13, 15), QPointF(17, 15))
    painter.end()
    return QIcon(pixmap)


class Switch(QCheckBox):
    """A keyboard-accessible checkbox with a compact switch indicator."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        return QSize(40 + self.fontMetrics().horizontalAdvance(self.text()), 30)

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        track = QRectF(1, (self.height() - 18) / 2, 30, 18)
        painter.setPen(Qt.NoPen)
        track_color = ("#137E74" if enabled else "#9FC6BA") if self.isChecked() else "#CBD5DC"
        painter.setBrush(QColor(track_color))
        painter.drawRoundedRect(track, 9, 9)
        painter.setBrush(QColor("white" if enabled else "#F2F5F7"))
        painter.drawEllipse(QRectF(track.x() + (15 if self.isChecked() else 3), track.y() + 3, 12, 12))
        painter.setPen(QColor("#273E4C" if enabled else "#93A1AB"))
        painter.drawText(self.rect().adjusted(41, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text())
        if self.hasFocus():
            painter.setPen(QPen(QColor("#137E74"), 1, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(track.adjusted(-1, -2, 2, 2), 10, 10)


class ElidedLabel(QLabel):
    """Keep long paths and live messages from stretching the workspace."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideMiddle, self.width())
        painter.drawText(self.rect(), self.alignment() | Qt.AlignVCenter, text)


class MetricCard(QFrame):
    def __init__(self, title, mark, tone, note):
        super().__init__()
        self.setObjectName("metricCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(96)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(4)
        caption = QLabel(title)
        caption.setObjectName("metricCaption")
        top.addWidget(caption)
        top.addStretch()
        symbol = QLabel()
        symbol.setPixmap(icon(mark, COLORS[tone][0], 18).pixmap(18, 18))
        top.addWidget(symbol)
        layout.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.value = QLabel("0")
        self.value.setObjectName("metricValue")
        self.value.setProperty("tone", tone)
        bottom.addWidget(self.value)
        self.note = QLabel(note)
        self.note.setObjectName("metricNote")
        self.note.setAlignment(Qt.AlignBottom | Qt.AlignLeft)
        self.note.setWordWrap(True)
        bottom.addWidget(self.note, 1)
        layout.addLayout(bottom)


class PeopleDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if index.column() not in (4, 5):
            super().paint(painter, option, index)
            return
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        style_option.text = ""
        style = option.widget.style()
        style.drawControl(QStyle.CE_ItemViewItem, style_option, painter, option.widget)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        font = option.font
        font.setPixelSize(11)
        painter.setFont(font)
        status = index.data(Qt.UserRole + 1) or "pending"
        foreground, background = COLORS[STATUS_TONES.get(status, "neutral")]
        if index.column() == 4:
            text = index.data() or ""
            width = min(option.rect.width() - 12, painter.fontMetrics().horizontalAdvance(text) + 18)
            pill = QRectF(option.rect.x() + 6, option.rect.center().y() - 11, width, 23)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(pill, 6, 6)
            painter.setPen(QColor(foreground))
            painter.drawText(pill, Qt.AlignCenter, text)
        else:
            value = float((index.data() or "0%").rstrip("%"))
            track = QRectF(option.rect.x() + 10, option.rect.center().y() - 2, max(12, option.rect.width() - 53), 4)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#E6ECEF"))
            painter.drawRoundedRect(track, 2, 2)
            if value > 0:
                filled = QRectF(track)
                filled.setWidth(track.width() * min(100, max(0, value)) / 100)
                painter.setBrush(QColor(foreground if status != "pending" else "#A6B5BF"))
                painter.drawRoundedRect(filled, 2, 2)
            painter.setPen(QColor("#617684"))
            painter.drawText(option.rect.adjusted(0, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, f"{value:.0f}%")
        painter.restore()


class PeopleTable(QTableWidget):
    def __init__(self, empty_title, empty_note):
        super().__init__(0, 8)
        self.setItemDelegate(PeopleDelegate(self))
        self.empty_state = QFrame(self.viewport())
        self.empty_state.setObjectName("emptyState")
        self.empty_state.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self.empty_state)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        layout.addStretch()
        symbol = QLabel()
        symbol.setObjectName("emptySymbol")
        symbol.setFixedSize(64, 64)
        symbol.setPixmap(icon("people", "#7A999F", 32).pixmap(32, 32))
        symbol.setAlignment(Qt.AlignCenter)
        layout.addWidget(symbol, 0, Qt.AlignCenter)
        title = QLabel(empty_title)
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        note = QLabel(empty_note)
        note.setObjectName("emptyNote")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "empty_state"):
            self.empty_state.setGeometry(self.viewport().rect())

    def setRowCount(self, count):
        super().setRowCount(count)
        if hasattr(self, "empty_state"):
            self.empty_state.setVisible(count == 0)
            self.empty_state.setGeometry(self.viewport().rect())


def stylesheet():
    assets = Path(__file__).with_name("assets").as_posix()
    return """
    QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #243D4B; }
    QMainWindow, QWidget#workspace { background: #F2F5F6; }
    QLabel { background: transparent; border: none; }
    QLabel#brandTitle { font-family: 'Segoe UI'; font-size: 25px; font-weight: 700; color: #183B43; }
    QLabel#brandSubtitle, QLabel#expiryCaption { color: #7A8B96; font-size: 11px; }
    QLabel#versionBadge { background: #E5ECEF; color: #68808E; border-radius: 5px; padding: 3px 8px; font-size: 11px; }
    QLabel#runBadge { background: #E7F4F0; color: #137E74; border-radius: 13px; padding: 6px 14px; font-size: 12px; }
    QLabel#runBadge[tone='neutral'] { background: #E5ECEF; color: #6D7E89; }
    QLabel#runBadge[tone='amber'] { background: #FFF0DE; color: #AD6A25; }
    QFrame#configPanel, QFrame#peoplePanel, QFrame#logPanel, QFrame#metricCard {
        background: #FFFFFF; border: 1px solid #DFE7EB; border-radius: 12px;
    }
    QLabel#panelTitle { font-size: 16px; font-weight: 600; color: #243D4B; }
    QLabel#panelCaption, QLabel#fieldHint, QLabel#identitySummary { color: #778C99; font-size: 11px; }
    QLabel#fieldLabel { color: #465E6C; font-size: 12px; font-weight: 600; }
    QFrame#modeOption { background: #EFF7F5; border: 1px solid #D7EAE4; border-radius: 9px; }
    QLabel#modeDescription { color: #65837D; font-size: 11px; }
    QFrame#workflowCard { background: #F6F8FA; border: none; border-radius: 9px; }
    QLabel#stepNumber { background: #E6EDF0; color: #6C8490; border-radius: 10px; font-size: 10px; font-weight: 600; }
    QLabel#stepTitle { font-size: 12px; color: #415B69; }
    QLabel#stepNote { color: #7E919D; font-size: 11px; }
    QFrame#divider { background: #EDF1F3; border: none; max-height: 1px; }
    QLineEdit, QComboBox, QSpinBox {
        background: #F8FAFB; border: 1px solid #DDE5EA; border-radius: 7px;
        padding: 8px 10px; selection-background-color: #CBE7DE; selection-color: #183B43;
    }
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #B6C8CE; }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #137E74; background: white; }
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #98A6AF; background: #F1F4F6; border-color: #E6ECEF; }
    QComboBox { padding-right: 27px; font-size: 12px; }
    QComboBox::drop-down { border: none; width: 27px; }
    QComboBox::down-arrow { image: url('__ASSETS__/chevron-down.svg'); width: 12px; height: 12px; }
    QComboBox QAbstractItemView { background: white; border: 1px solid #DDE5EA; padding: 4px; selection-background-color: #E7F4F0; selection-color: #137E74; outline: none; }
    QSpinBox { padding-right: 25px; }
    QSpinBox::up-button, QSpinBox::down-button { width: 23px; border: none; background: transparent; }
    QSpinBox::up-arrow { image: url('__ASSETS__/chevron-up.svg'); width: 10px; height: 10px; }
    QSpinBox::down-arrow { image: url('__ASSETS__/chevron-down.svg'); width: 10px; height: 10px; }
    QCheckBox { spacing: 8px; background: transparent; }
    QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #C2D0D7; border-radius: 4px; background: white; }
    QCheckBox::indicator:checked { background: #137E74; border-color: #137E74; image: url('__ASSETS__/check.svg'); }
    QCheckBox::indicator:disabled { background: #E7ECEF; border-color: #DAE2E7; }
    QCheckBox:disabled { color: #98A6AF; }
    QPushButton {
        min-height: 18px; padding: 8px 12px; border: 1px solid #DBE4E9;
        border-radius: 7px; background: #FFFFFF; font-size: 12px;
    }
    QPushButton:hover { background: #F2F7F6; border-color: #B5CBC5; }
    QPushButton:pressed { background: #E8F1EE; }
    QPushButton:focus { border-color: #137E74; }
    QPushButton:disabled { color: #ABB7BF; border-color: #E6ECEF; background: #F7F9FA; }
    QPushButton#startWatch { background: #137E74; color: white; border-color: #137E74; font-size: 13px; font-weight: 600; padding: 10px 22px; }
    QPushButton#startWatch:hover { background: #106D65; border-color: #106D65; }
    QPushButton#startWatch:pressed { background: #0D5A54; }
    QPushButton#startWatch:disabled { background: #C8DCD6; border-color: #C8DCD6; color: #F4F8F6; }
    QPushButton#importIdentities { background: #EDF7F3; border-color: #C9E3D9; color: #137E74; }
    QPushButton#importIdentities:hover { background: #DEEFE8; }
    QPushButton#importIdentities:disabled { background: #F2F5F5; border-color: #E6ECEF; color: #A6B6B2; }
    QPushButton[role='quiet'] { border-color: transparent; background: transparent; color: #738794; }
    QPushButton[role='quiet']:hover { background: #EEF4F5; color: #137E74; }
    QPushButton[role='quiet']:disabled { color: #B2BDC4; }
    QPushButton#stopFlow { color: #AD6262; }
    QPushButton#stopFlow:hover { background: #FFF2F1; border-color: #E8C8C7; }
    QPushButton#stopFlow:disabled { color: #BAAFB1; }
    QToolButton { background: transparent; border: none; border-radius: 5px; padding: 5px; color: #738794; font-size: 11px; }
    QToolButton:hover { background: #EDF3F4; color: #137E74; }
    QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
    QScrollBar:vertical { width: 6px; background: transparent; margin: 3px 0; }
    QScrollBar::handle:vertical { background: #D6E0E5; border-radius: 3px; min-height: 28px; }
    QScrollBar::handle:vertical:hover { background: #B9CCD0; }
    QScrollBar:horizontal { height: 6px; background: transparent; }
    QScrollBar::handle:horizontal { background: #D6E0E5; border-radius: 3px; min-width: 28px; }
    QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
    QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
    QTabWidget::pane { border: none; background: transparent; }
    QTabBar { background: transparent; }
    QTabBar::tab { color: #7D8F9A; background: transparent; padding: 10px 12px; border-bottom: 2px solid transparent; margin-right: 8px; font-size: 12px; }
    QTabBar::tab:selected { color: #137E74; border-bottom-color: #137E74; font-weight: 600; }
    QTabBar::tab:hover:!selected { color: #3D6770; }
    QTabWidget#configTabs QTabBar::tab { padding: 9px 16px; margin-right: 5px; }
    QLabel#metricCaption { color: #7A8E9A; font-size: 12px; }
    QLabel#metricValue { color: #243D4B; font-family: 'Segoe UI'; font-size: 28px; font-weight: 600; }
    QLabel#metricValue[tone='teal'] { color: #137E74; }
    QLabel#metricValue[tone='blue'] { color: #3775B1; }
    QLabel#metricValue[tone='amber'] { color: #AD6A25; }
    QLabel#metricNote { color: #81949F; font-size: 10px; padding-bottom: 6px; }
    QTableWidget { background: white; border: none; gridline-color: #EDF2F4; outline: none; font-size: 12px; selection-background-color: #EDF6F3; selection-color: #243D4B; }
    QTableWidget::item { border-bottom: 1px solid #F0F3F5; padding: 0 6px; }
    QTableWidget::item:hover { background: #F6FAF9; }
    QTableWidget::item:selected { background: #EAF4F0; color: #243D4B; }
    QHeaderView { background: #F6F8FA; border: none; }
    QHeaderView::section { background: #F6F8FA; color: #80929F; font-size: 11px; font-weight: 400; padding: 10px 6px; border: none; }
    QTableCornerButton::section { border: none; background: #F6F8FA; }
    QFrame#emptyState { background: white; border: none; }
    QLabel#emptySymbol { background: #F0F5F5; border-radius: 22px; }
    QLabel#emptyTitle { color: #5D7782; font-size: 15px; font-weight: 600; }
    QLabel#emptyNote { color: #9AA9B2; font-size: 11px; }
    QLabel#queueCaption, QLabel#progressCaption { color: #8B9CA6; font-size: 11px; }
    QProgressBar { border: none; background: #EAF0F1; border-radius: 3px; max-height: 5px; min-height: 5px; }
    QProgressBar::chunk { border: none; background: #31988A; border-radius: 3px; }
    QFrame#resultStrip { background: #F6F8FA; border: none; border-radius: 8px; }
    QLabel#resultPath { color: #8A9BA6; font-size: 11px; }
    QLabel#logTitle { color: #5F7784; font-size: 12px; font-weight: 600; }
    QLabel#liveStatus { color: #8799A4; font-size: 11px; }
    QPlainTextEdit { background: #F7F9FA; border: none; border-radius: 7px; padding: 8px; color: #6B818E; font-size: 11px; selection-background-color: #D6EDE4; }
    QFrame#commandBar { background: #E8EFF0; border: 1px solid #DCE7E8; border-radius: 12px; }
    QLabel#commandTitle { color: #365A60; font-size: 13px; font-weight: 600; }
    QLabel#commandNote { color: #81979C; font-size: 11px; }
    QSplitter::handle { background: transparent; }
    QSplitter::handle:hover { background: #E1E9EC; border-radius: 3px; }
    QToolTip { color: #EAF1F1; background: #2B444D; border: none; padding: 7px 10px; }
    QMessageBox { background: #F7F9FA; }
    """.replace("__ASSETS__", assets)
