#!/usr/bin/env python3
"""TagBee - a small, fast music tag editor (drag & drop, batch edit, compilations).

Run:  python3 tagbee.py [files or folders...]
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import json
import subprocess
from PySide6.QtCore import QRectF, QBuffer, QByteArray, QEasingCurve, QEvent, QIODevice, QSettings, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QFont, QGuiApplication, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGraphicsDropShadowEffect, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressDialog,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

import tagio
import theme
from tagio import Track
from widgets import FieldBox, FlatButton, Segmented, eyebrow_font, symbol

APP_NAME = "TagBee"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
MULTI = "< keep >"
MIXED_HINT = "< keep >"          # Mp3tag's wording: the tracks differ, typing replaces all
CLEARED_HINT = "< blank >"
RENAME_PRESETS = [     # (button, pattern); the first is the default
    ("Title - Artist - Track", "%title% - %artist% - %track%"),
    ("Track - Artist - Title", "%track% - %artist% - %title%"),
    ("Artist - Title", "%artist% - %title%"),
]
BASE_PT = 13          # column widths below are designed for this text size
DEFAULT_PT = 16

# table column key, header, default width
COLUMNS = [
    ("file", "File", 150), ("track", "#", 38), ("title", "Title", 150),
    ("artist", "Artist", 120), ("album", "Album", 130), ("albumartist", "Album Artist", 110),
    ("date", "Year", 50), ("genre", "Genre", 80), ("compilation", "Comp.", 66),
    ("format", "Format", 92), ("length", "Time", 58),
]
COLUMN_INDEX = {key: i for i, (key, _, _) in enumerate(COLUMNS)}
SECONDARY_COLUMNS = {"artist", "album", "albumartist", "date", "genre", "length"}   # dimmer text, like MacBee rows


def resource_path(name: str):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for cand in (base / name, base.parent / "Resources" / name):
        if cand.exists():
            return cand
    return None


def natural_key(s: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def fmt_time(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_duration(sec: float) -> str:
    """Total time for the status bar: 4:05, 1:02:09."""
    sec = int(round(sec))
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def rounded(pix: QPixmap, side: int, dpr: float) -> QPixmap:
    """Square cover with MacBee's rounded corners."""
    px = int(side * dpr)
    src = pix.scaled(px, px, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(px, px); out.fill(Qt.transparent)
    p = QPainter(out); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath(); path.addRoundedRect(QRectF(0, 0, px, px), theme.CORNER * dpr, theme.CORNER * dpr)
    p.setClipPath(path)
    p.drawPixmap(int((px - src.width()) / 2), int((px - src.height()) / 2), src); p.end()
    out.setDevicePixelRatio(dpr)
    return out


class RowHoverDelegate(QStyledItemDelegate):
    """Highlights the whole row under the mouse, like MacBee's track rows; draws format badges."""

    def __init__(self, table: QTableWidget, tokens, badge_col: int):
        super().__init__(table)
        self.table, self.tokens, self.badge_col, self.row = table, tokens, badge_col, -1   # tokens: callable -> Theme
        table.setMouseTracking(True)
        table.viewport().installEventFilter(self)
        table.verticalScrollBar().valueChanged.connect(lambda _: self.track_cursor())

    def track_cursor(self):
        pos = self.table.viewport().mapFromGlobal(QCursor.pos())
        self.set_row(self.table.rowAt(pos.y()) if self.table.viewport().rect().contains(pos) else -1)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseMove:
            self.set_row(self.table.rowAt(e.position().toPoint().y()))
        elif e.type() == QEvent.Leave:
            self.set_row(-1)
        return False

    def set_row(self, row: int):
        if row != self.row:
            self.row = row
            self.table.viewport().update()

    def paint(self, painter, option, index):
        t = self.tokens()
        if index.row() == self.row and not option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, t.surface)
        tint = index.data(Qt.BackgroundRole)      # the stylesheet hides item backgrounds, so paint the unsaved tint here
        if tint is not None and tint.color().alpha():
            painter.fillRect(option.rect, tint)
        if index.column() == self.badge_col and index.data():
            opt = QStyleOptionViewItem(option); self.initStyleOption(opt, index); opt.text = ""
            opt.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
            self.paint_badge(painter, option.rect, index.data(), bool(index.data(Qt.UserRole + 2)), t)
            return
        super().paint(painter, option, index)

    @staticmethod
    def paint_badge(painter, rect, text: str, hires: bool, t):
        """MacBee QualityBadge: tiny semibold text in a thin rounded outline; accent for hi-res."""
        painter.save(); painter.setRenderHint(QPainter.Antialiasing)
        f = eyebrow_font(painter.font()); f.setLetterSpacing(QFont.AbsoluteSpacing, 0.3); painter.setFont(f)
        color = t.accent_text if hires else t.text_tertiary
        fm = painter.fontMetrics()
        w = min(rect.width() - 10, fm.horizontalAdvance(text) + 10); h = fm.height() + 2
        box = QRectF(rect.x() + 6, rect.center().y() - h / 2 + 0.5, w, h)
        painter.setPen(QPen(t.tint(color, 0.7), 1)); painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(color)
        painter.drawText(box, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, int(w - 6)))
        painter.restore()


class CoverLabel(QLabel):
    """Cover art: a soft shadow fades in on hover (150 ms ease-out), like MacBee's album cards."""

    def __init__(self):
        super().__init__()
        self.setObjectName("cover")
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setOffset(0, 6)
        self.setGraphicsEffect(self.shadow)
        self._level = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(theme.HOVER_MS)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._step)
        self._step(0.0)

    def _step(self, v):
        self._level = float(v)
        self.shadow.setBlurRadius(4 + 24 * self._level)
        self.shadow.setColor(QColor(0, 0, 0, int(40 + 120 * self._level)))

    def _fade_to(self, end: float):
        self.anim.stop()
        self.anim.setStartValue(self._level)
        self.anim.setEndValue(end)
        self.anim.start()

    def enterEvent(self, e):
        self._fade_to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._fade_to(0.0)
        super().leaveEvent(e)


def swatch(color: str) -> QIcon:
    """Small round colour dot for the Accent Color menu."""
    pix = QPixmap(28, 28); pix.fill(Qt.transparent)
    p = QPainter(pix); p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen); p.setBrush(QColor(color)); p.drawEllipse(3, 3, 22, 22); p.end()
    return QIcon(pix)


class SortItem(QTableWidgetItem):
    """Table item that sorts by a key stored in UserRole+1 (numbers sort as numbers)."""

    def __lt__(self, other):
        a, b = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


# --------------------------------------------------------------------------- dialogs

class CompilationDialog(QDialog):
    def __init__(self, parent, album_hint: str):
        super().__init__(parent)
        self.setWindowTitle("Make Compilation")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        info = QLabel(
            "Each track keeps its own <b>Artist</b>. The <b>Album Artist</b> is set to one name "
            "and the <b>Compilation</b> flag is turned on, so players group the album together "
            "and don't add every artist to your artist list."
        )
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.album_artist = QLineEdit("Various Artists")
        self.album = QLineEdit(album_hint)
        self.album.setPlaceholderText("(leave blank to keep each track's album)")
        self.number = QCheckBox("Number tracks 1…N in the current list order")
        self.number.setToolTip("Also sets the track total.")
        form.addRow("Album Artist", self.album_artist)
        form.addRow("Album", self.album)
        form.addRow("", self.number)
        lay.addLayout(form)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)


class AutoNumberDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Auto-number Tracks")
        form = QFormLayout(self)
        self.start = QSpinBox(); self.start.setRange(0, 9999); self.start.setValue(1)
        self.total = QCheckBox("Set track total to the number of selected tracks"); self.total.setChecked(True)
        self.disc = QLineEdit(); self.disc.setPlaceholderText("(leave blank to keep)")
        self.disc.setMaximumWidth(120)
        form.addRow("Start at", self.start)
        form.addRow("Disc number", self.disc)
        form.addRow("", self.total)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        form.addRow(box)


class RenameDialog(QDialog):
    def __init__(self, parent, tracks: list[Track]):
        super().__init__(parent)
        self.tracks = tracks
        self.setWindowTitle("Rename Files from Tags")
        self.resize(640, 440)
        lay = QVBoxLayout(self)
        presets = QHBoxLayout(); presets.setSpacing(6)
        lab = QLabel("Presets:"); lab.setObjectName("muted"); presets.addWidget(lab)
        for name, pattern in RENAME_PRESETS:
            b = QPushButton(name); b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, p=pattern: self.pattern.setText(p))
            presets.addWidget(b)
        presets.addStretch(1)
        lay.addLayout(presets)
        self.pattern = QLineEdit(RENAME_PRESETS[0][1])
        self.pattern.setToolTip("Fields you can use: %track% %disc% %title% %artist% %album% %albumartist% %date% %genre%")
        lay.addWidget(self.pattern)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Current name", "New name"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        warn = QLabel("Files are renamed on disk immediately.")
        lay.addWidget(warn)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("Rename")
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.pattern.textChanged.connect(self.update_preview)
        self.update_preview()

    def new_stem(self, track: Track) -> str:
        return tagio.format_filename(self.pattern.text(), track.tags)

    def update_preview(self):
        self.table.setRowCount(len(self.tracks))
        for i, t in enumerate(self.tracks):
            stem = self.new_stem(t)
            self.table.setItem(i, 0, QTableWidgetItem(t.path.name))
            self.table.setItem(i, 1, QTableWidgetItem(stem + t.path.suffix if stem else "(unchanged)"))


class CompilationCheck(QCheckBox):
    """Mp3tag's Compilation checkbox. A dash (partly checked) = the selected tracks differ."""
    chosen = Signal(str)          # "1" or ""

    def __init__(self):
        super().__init__("Compilation")
        self.setToolTip("Players show these tracks as one album; each track keeps its own Artist")
        self.clicked.connect(self._clicked)

    def _clicked(self, on: bool):
        self.setTristate(False)
        self.setChecked(on)
        self.chosen.emit("1" if on else "")

    def set_state(self, value, show_label=True):
        """value: "1", "" or None (mixed / nothing selected)."""
        self.setTristate(value is None and show_label)
        self.setCheckState(Qt.PartiallyChecked if (value is None and show_label)
                           else Qt.Checked if value == "1" else Qt.Unchecked)


class DropArea(QWidget):
    """The empty track list: a dashed box to drop music on, or click to choose files."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("dropzone")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self); lay.setSpacing(8)
        self.icon = QLabel(); self.icon.setAlignment(Qt.AlignCenter)
        self.title = QLabel("Drop music here"); self.title.setAlignment(Qt.AlignCenter); self.title.setObjectName("emptytitle")
        self.detail = QLabel("Drag files or folders from Finder into this space\n"
                             "FLAC · M4A · MP3 · OGG · OPUS · WAV · AIFF\n\nor click to choose files (⌘O)")
        self.detail.setAlignment(Qt.AlignCenter); self.detail.setObjectName("muted")
        lay.addStretch(1); lay.addWidget(self.icon); lay.addWidget(self.title); lay.addWidget(self.detail); lay.addStretch(1)

    def mousePressEvent(self, e):
        self.clicked.emit()


class PreferencesDialog(QDialog):
    """Preferences ▸ Appearance, with MacBee's settings: theme, accent colour, sidebar width (plus text size)."""
    THEMES = [("system", "System"), ("dark", "Dark"), ("gray", "Medium Gray"), ("light", "Light")]

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self); lay.setContentsMargins(22, 18, 22, 18); lay.setSpacing(6)
        head = QLabel("Appearance"); f = QFont(self.font()); f.setPointSizeF(f.pointSizeF() * 1.3); f.setBold(True)
        head.setFont(f); lay.addWidget(head)

        def section(title):
            lay.addSpacing(12)
            l = QLabel(title.upper()); l.setObjectName("section"); l.setFont(eyebrow_font(self.font())); lay.addWidget(l)

        section("Theme")
        self.theme_btns = {}
        for key, label in self.THEMES:
            b = FlatButton(label, None, "segment"); b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.pick_theme(k))
            self.theme_btns[key] = b
        lay.addWidget(Segmented(*self.theme_btns.values()), 0, Qt.AlignLeft)

        section("Accent color")
        row = QHBoxLayout(); row.setSpacing(10)
        self.swatches = {}
        for key, label, color in theme.ACCENT_CHOICES:
            b = QToolButton(); b.setToolTip(label); b.setFixedSize(26, 26); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=color: self.pick_accent(c))
            self.swatches[color.lower()] = b; row.addWidget(b)
        custom = QPushButton("Custom…"); custom.clicked.connect(self.custom_accent); custom.setAutoDefault(False)
        self.custom_mark = QLabel("✓")
        row.addSpacing(6); row.addWidget(custom); row.addWidget(self.custom_mark); row.addStretch(1)
        lay.addLayout(row)
        n = QLabel("Used for buttons, highlights and edited fields."); n.setObjectName("faint"); lay.addWidget(n)

        section("Sidebar")
        self.width_slider = self.slider(win.SIDEBAR_RANGE, win.sidebar_width, win.set_sidebar_width, "Narrow", "Wide")
        n = QLabel("The width when the sidebar is expanded. Collapsed, it always shows icons only.")
        n.setObjectName("faint"); n.setWordWrap(True); lay.addWidget(n)

        section("Text size")
        self.text_slider = self.slider((10, 28), win.font_pt, lambda v: win.change_font(v - win.font_pt), "Smaller", "Larger")
        n = QLabel("Same as View ▸ Larger / Smaller Text (⌘+ / ⌘-)."); n.setObjectName("faint"); lay.addWidget(n)

        lay.addSpacing(14)
        close = QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(self.accept)
        lay.addWidget(close)
        self.refresh()

    def slider(self, rng, value, slot, lo, hi):
        from PySide6.QtWidgets import QSlider
        h = QHBoxLayout(); h.setSpacing(10)
        s = QSlider(Qt.Horizontal); s.setRange(*rng); s.setValue(int(value))
        s.valueChanged.connect(slot)
        a, b = QLabel(lo), QLabel(hi)
        for l in (a, b):
            l.setObjectName("faint")
        h.addWidget(a); h.addWidget(s, 1); h.addWidget(b)
        self.layout().addLayout(h)
        return s

    def pick_theme(self, key):
        self.win.set_theme(key)
        self.refresh()

    def pick_accent(self, color):
        self.win.set_accent(color)
        self.refresh()

    def custom_accent(self):
        self.win.pick_accent()
        self.refresh()

    def refresh(self):
        for key, b in self.theme_btns.items():
            b.setChecked(key == self.win.theme)
        cur = self.win.accent.lower()
        ring = theme.current.text_primary.name()
        for color, b in self.swatches.items():
            border = f"2px solid {ring}" if color == cur else "2px solid transparent"
            b.setStyleSheet(f"QToolButton {{ background: {color}; border-radius: 13px; border: {border}; }}")
        self.custom_mark.setVisible(cur not in self.swatches)


# --------------------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    SIDEBAR_RANGE = (170, 340)      # expanded sidebar width in points (MacBee's slider, scaled for TagBee's larger text)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # first launch: a modest landscape window in the middle of the screen; later, wherever you left it
        w, h = (min(1180, int(avail.width() * 0.8)), min(720, int(avail.height() * 0.75))) if avail else (1180, 720)
        self.resize(w, h)
        if avail:
            self.move(avail.x() + (avail.width() - w) // 2, avail.y() + (avail.height() - h) // 2)
        self.setAcceptDrops(True)
        self.tracks: dict[int, Track] = {}
        self._next_uid = 0
        self._populating = False
        self._sort_col, self._sort_order = None, Qt.AscendingOrder
        self.panel_tracks: list[Track] = []      # tracks currently shown in the editor panel
        self.panel_orig: dict[str, list[str]] = {}   # each field's values when the tracks were selected
        self.draft: dict[str, str] = {}               # edits typed but not applied yet
        self.draft_art = None                          # cover change not applied yet

        self.settings = QSettings("TagBee", "TagBee")
        self.migrate_old_settings()
        geometry = self.settings.value("windowGeometry")
        if geometry:
            self.restoreGeometry(geometry)
        try:
            self.font_pt = max(10, min(32, int(self.settings.value("fontSize", DEFAULT_PT))))
        except (TypeError, ValueError):
            self.font_pt = DEFAULT_PT
        self.theme = str(self.settings.value("theme", theme.DEFAULT_THEME))
        if self.theme not in dict(theme.THEME_CHOICES):
            self.theme = theme.DEFAULT_THEME
        self.accent = str(self.settings.value("accent", theme.DEFAULT_ACCENT))
        self.tokens = theme.Theme.make(theme.DEFAULT_THEME, self.accent)
        self._build_ui()
        self._build_actions()
        self.panel_scroll.installEventFilter(self)
        self.apply_theme()
        self.apply_font()
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self.theme == "system" and self.apply_theme())
        self.populate_panel([])
        self.update_status()

    # ---- UI construction: sidebar | track list | inspector
    def _build_ui(self):
        # ===== left sidebar: add, tools (files are dropped on the track list). Collapses to an icon rail.
        self.sidebar = QWidget(); self.sidebar.setObjectName("sidebar")
        self.sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sb = QVBoxLayout(self.sidebar); sb.setContentsMargins(8, 14, 8, 12); sb.setSpacing(2)
        self.sidebar_collapsed = self.settings.value("sidebarCollapsed", False, type=bool)
        try:
            self.sidebar_width = int(self.settings.value("sidebarWidth", 230))
        except (TypeError, ValueError):
            self.sidebar_width = 230
        self.sidebar_width = max(self.SIDEBAR_RANGE[0], min(self.SIDEBAR_RANGE[1], self.sidebar_width))
        self.sidebar_rows: list[tuple[FlatButton, str]] = []
        self.sidebar_sections: list[QLabel] = []

        # header like MacBee's: small app icon + bold name, and the collapse button
        brand = QHBoxLayout(); brand.setContentsMargins(10, 0, 0, 0); brand.setSpacing(9)
        self.logo = QLabel()
        self.brand_title = QLabel(APP_NAME); self.brand_title.setObjectName("brand")
        self.collapse_btn = FlatButton("", "sidebar.left", "plain", "Hide or show the sidebar (⌃⌘S)")
        self.collapse_btn.clicked.connect(self.toggle_sidebar)
        brand.addWidget(self.logo); brand.addWidget(self.brand_title, 1); brand.addWidget(self.collapse_btn)
        self.brand_row = brand
        sb.addLayout(brand)
        sb.addSpacing(10)

        def row(text, icon, slot, tip=None):
            b = FlatButton(text, icon, "row", tip or text)
            b.clicked.connect(slot)
            sb.addWidget(b)
            self.sidebar_rows.append((b, text))

        def section(text):
            l = QLabel(text.upper()); l.setObjectName("section"); l.setContentsMargins(10, 0, 0, 2)
            sb.addSpacing(12); sb.addWidget(l)
            self.sidebar_sections.append(l)

        row("Add Files…", "doc.badge.plus", self.add_files_dialog, "Choose audio files (⌘O)")
        row("Add Folder…", "folder.badge.plus", self.add_folder_dialog, "Add every audio file in a folder (⇧⌘O)")
        section("Tools")
        row("Make Compilation", "opticaldisc", self.make_compilation, "Set Album Artist + Compilation flag, keep each track's artist (⌘K)")
        row("Auto-number", "list.number", self.auto_number, "Number the selected tracks in list order")
        row("Rename Files", "character.cursor.ibeam", self.rename_files, "Rename files from their tags")
        section("List")
        row("Select All", "checkmark.circle", self.select_all, "Select every track in the list (⌘A)")
        row("Select None", "circle", self.select_none, "Deselect all tracks (⇧⌘A)")
        row("Remove Selected", "minus.circle", self.remove_selected, "Remove from this window only (files aren't touched)")
        row("Clear List", "trash", self.clear_list, "Remove everything from this window (files aren't touched)")
        sb.addStretch(1)

        # ===== middle: track list (with an empty-state hint)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1].upper() for c in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setItemDelegate(RowHoverDelegate(self.table, lambda: self.tokens, COLUMN_INDEX["format"]))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.row_menu)
        hh = self.table.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setMinimumSectionSize(36)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i, (key, _, _) in enumerate(COLUMNS):
            if key in ("title", "artist", "album"):
                hh.setSectionResizeMode(i, QHeaderView.Stretch)   # always share the free width, so Album is visible
        hh.setContextMenuPolicy(Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self.header_menu)
        for i, (_, _, w) in enumerate(COLUMNS):
            self.table.setColumnWidth(i, w)
        hh.sectionClicked.connect(self.on_header_clicked)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        try:
            for i in json.loads(str(self.settings.value("hiddenCols", "[5, 6, 7, 9, 10]"))):   # Album Artist, Year, Genre, Format, Time (right-click the headings to show)
                if 0 < i < len(COLUMNS):
                    self.table.setColumnHidden(i, True)
        except (ValueError, TypeError):
            pass

        # empty state: a dashed drop box; with tracks loaded, a quiet notice under the list
        self.drop_area = DropArea()
        self.drop_area.clicked.connect(self.add_files_dialog)
        empty = QWidget(); el = QVBoxLayout(empty); el.setContentsMargins(24, 24, 24, 24)
        el.addWidget(self.drop_area)
        self.drop_note = QLabel("Drop more files or folders anywhere here to add them")
        self.drop_note.setObjectName("faint"); self.drop_note.setAlignment(Qt.AlignCenter)
        self.drop_note.setContentsMargins(0, 6, 0, 6)
        listed = QWidget(); ll = QVBoxLayout(listed); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(0)
        ll.addWidget(self.table, 1); ll.addWidget(self.drop_note)
        self.stack = QStackedWidget(); self.stack.setObjectName("center")
        self.stack.addWidget(empty)
        self.stack.addWidget(listed)

        # ===== right: tag panel laid out like Mp3tag's (label above each field, cover below).
        # Typing drafts an edit; Apply puts it on the selected tracks; Commit to File writes them.
        self.panel_title = QLabel(); self.panel_title.setObjectName("muted")
        self.panel_title.setTextFormat(Qt.PlainText)

        self.widgets: dict[str, QWidget] = {}
        self.menu_actions: list[QAction] = []

        def line(key):
            w = QLineEdit()
            w.textEdited.connect(lambda text, k=key: self.on_field_edited(k, text))
            w.returnPressed.connect(self.apply_draft)
            a = w.addAction(QIcon(), QLineEdit.TrailingPosition)
            a.setToolTip("< keep >, < blank >, or a value from the selected tracks")
            a.triggered.connect(lambda _=False, k=key: self.value_menu(k))
            self.menu_actions.append(a)
            self.widgets[key] = w
            return w

        self.comp_check = CompilationCheck()
        self.comp_check.chosen.connect(lambda v: self.on_field_edited("compilation", v))
        self.widgets["compilation"] = self.comp_check

        self.lyrics = QPlainTextEdit()
        self.lyrics.setFixedHeight(90)
        self.lyrics.textChanged.connect(self.on_lyrics_changed)
        self.widgets["lyrics"] = self.lyrics

        def labelled(label, widget):
            cell = QWidget()
            v = QVBoxLayout(cell); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(1)
            lab = QLabel(label + ":"); lab.setObjectName("taglabel")
            v.addWidget(lab); v.addWidget(widget)
            return cell

        def column(target):
            def add(label, widget):
                target.addWidget(labelled(label, widget))

            def row(*cells):        # (label, widget, stretch) side by side
                h = QHBoxLayout(); h.setSpacing(6)
                for label, widget, stretch in cells:
                    h.addWidget(labelled(label, widget) if label else widget, stretch)
                target.addLayout(h)
            return add, row

        fields = QVBoxLayout(); fields.setSpacing(4)
        add, row = column(fields)
        add("Title", line("title"))
        add("Artist", line("artist"))
        add("Album", line("album"))
        row(("Year", line("date"), 3), ("Track", line("track"), 3), ("Genre", line("genre"), 5))
        add("Comment", line("comment"))
        add("Album Artist", line("albumartist"))
        add("Composer", line("composer"))
        disc = labelled("Disc Number", line("disc"))
        h = QHBoxLayout(); h.setSpacing(10)
        h.addWidget(disc, 3); h.addWidget(self.comp_check, 8, Qt.AlignBottom)
        fields.addLayout(h)

        # cover, full width like Mp3tag (right-click it to replace or remove)
        self.art_label = CoverLabel()
        self.art_label.setAlignment(Qt.AlignCenter)
        self.art_label.setWordWrap(True)
        self.art_label.setToolTip("Drop an image on the window, or right-click, to change the cover")
        self.art_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.art_label.customContextMenuRequested.connect(self.cover_menu)
        self.art_info = QLabel(); self.art_info.setObjectName("faint")
        self.art_info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # never widens the panel
        replace_btn = FlatButton("Replace…", "photo", "plain", "Choose a new cover image")
        replace_btn.clicked.connect(self.choose_cover)
        remove_btn = FlatButton("Remove", "trash", "plain", "Remove the cover")
        remove_btn.clicked.connect(self.remove_cover)
        art_row = QHBoxLayout(); art_row.setSpacing(2)
        art_row.addWidget(self.art_info, 1); art_row.addWidget(replace_btn); art_row.addWidget(remove_btn)

        # everything else TagBee edits, folded away under the main fields (the cover stays last)
        self.more_btn = FlatButton("More fields", "chevron.right", "plain", "Totals, BPM, grouping, copyright, lyrics, sort names")
        self.more_btn.setCheckable(True)
        more_inner = QWidget(); ml = QVBoxLayout(more_inner); ml.setContentsMargins(0, 0, 0, 0); ml.setSpacing(4)
        add2, row2 = column(ml)
        row2(("Total Tracks", line("tracktotal"), 1), ("Total Discs", line("disctotal"), 1), ("BPM", line("bpm"), 1))
        add2("Grouping", line("grouping"))
        add2("Copyright", line("copyright"))
        add2("Lyrics", self.lyrics)
        for key in ("titlesort", "artistsort", "albumsort", "albumartistsort"):
            add2(tagio.LABELS[key], line(key))

        def show_more(on):
            more_inner.setVisible(on)
            self.more_btn.icon_name = "chevron.down" if on else "chevron.right"
            self.more_btn.update()
            self.settings.setValue("moreFields", on)
        self.more_btn.toggled.connect(show_more)
        self.more_btn.setChecked(self.settings.value("moreFields", False, type=bool))
        show_more(self.more_btn.isChecked())

        # order like Mp3tag: tag fields, then the cover last
        panel_layout = QVBoxLayout(); panel_layout.setContentsMargins(10, 8, 10, 8); panel_layout.setSpacing(4)
        panel_layout.addWidget(self.panel_title)
        panel_layout.addLayout(fields)
        panel_layout.addWidget(self.more_btn, 0, Qt.AlignLeft)
        panel_layout.addWidget(more_inner)
        panel_layout.addSpacing(4)
        panel_layout.addLayout(art_row)
        panel_layout.addWidget(self.art_label)
        panel_layout.addStretch(1)
        self.panel = QWidget(); self.panel.setLayout(panel_layout); self.panel.setObjectName("inspectorPanel")
        scroll = QScrollArea(); scroll.setWidget(self.panel); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.panel_scroll = scroll

        # Apply · Revert · Commit to File
        self.apply_btn = FlatButton("Apply", "checkmark", "capsule", "Put your edits on the selected tracks (⌘↩ or Return). Not written yet.")
        self.apply_btn.setShortcut("Ctrl+Return")
        self.apply_btn.clicked.connect(self.apply_draft)
        self.revert_btn = FlatButton("Revert", "arrow.uturn.backward", "plain",
                                     "Throw away edits, or undo the selected tracks' unsaved changes (⌘R)")
        self.revert_btn.clicked.connect(self.revert)
        self.save_btn = FlatButton("Commit to File", "square.and.arrow.down", "accent",
                                   "Apply any edits and write every changed track into its file (⌘S)")
        self.save_btn.clicked.connect(self.save_all)
        bar = QHBoxLayout(); bar.setContentsMargins(10, 6, 10, 8); bar.setSpacing(4)
        bar.addWidget(self.apply_btn); bar.addWidget(self.revert_btn); bar.addStretch(1); bar.addWidget(self.save_btn)
        self.right = QWidget(); self.right.setObjectName("inspector")
        self.right.setAttribute(Qt.WA_StyledBackground, True)
        rl = QVBoxLayout(self.right); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0)
        rl.addWidget(scroll, 1)
        sep = QFrame(); sep.setObjectName("divider"); rl.addWidget(sep)
        holder = QWidget(); holder.setLayout(bar); rl.addWidget(holder)

        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        split.addWidget(self.sidebar); split.addWidget(self.stack); split.addWidget(self.right)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setStretchFactor(2, 0)
        self.split = split
        self.setCentralWidget(split)

    def header_menu(self, pos):
        """Right-click the column headings to show/hide columns."""
        menu = QMenu(self)
        for i, (key, label, _) in enumerate(COLUMNS):
            if key == "file":
                continue
            a = menu.addAction(label); a.setCheckable(True)
            a.setChecked(not self.table.isColumnHidden(i))
            a.toggled.connect(lambda on, i=i: self.set_column_hidden(i, not on))
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def row_menu(self, pos):
        """Right-click a track: the usual tools, plus Show in Finder."""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        if not self.table.item(row, 0).isSelected():
            self.table.selectRow(row)
        menu = QMenu(self)
        menu.addActions([self.act_comp, self.act_number, self.act_rename]); menu.addSeparator()
        menu.addAction("Show in Finder", self.show_in_finder); menu.addSeparator()
        menu.addActions([self.act_revert, self.act_remove])
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def select_all(self):
        self.table.selectAll()

    def select_none(self):
        self.table.clearSelection()

    def show_in_finder(self):
        paths = [str(t.path) for t in self.selected_tracks()]
        if paths:
            subprocess.run(["open", "-R", *paths[:20]], check=False)

    def set_column_hidden(self, i: int, hidden: bool):
        self.table.setColumnHidden(i, hidden)
        self.settings.setValue("hiddenCols", json.dumps([c for c in range(len(COLUMNS)) if self.table.isColumnHidden(c)]))

    def _build_actions(self):
        def act(text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            if tip:
                a.setToolTip(tip); a.setStatusTip(tip)
            return a

        self.act_add = act("Add Files…", self.add_files_dialog, QKeySequence.Open)
        self.act_add_folder = act("Add Folder…", self.add_folder_dialog, "Ctrl+Shift+O")
        self.act_save = act("Commit to File", self.save_all, QKeySequence.Save, "Write all changes into the original files")
        self.act_revert = act("Revert", self.revert, "Ctrl+R", "Discard unsaved changes on the selected tracks")
        self.act_remove = act("Remove from List", self.remove_selected, QKeySequence.Delete, "Remove from this window (files aren't touched)")
        self.act_clear = act("Clear List", self.clear_list)
        self.act_comp = act("Make Compilation…", self.make_compilation, "Ctrl+K", "Set Album Artist + Compilation flag, keep track artists")
        self.act_number = act("Auto-number…", self.auto_number, None, "Number the selected tracks in list order")
        self.act_rename = act("Rename Files…", self.rename_files, None, "Rename files from their tags")
        self.act_selall = act("Select All", self.select_all, QKeySequence.SelectAll)
        self.act_selnone = act("Select None", self.select_none, "Ctrl+Shift+A")

        m = self.file_menu = self.menuBar().addMenu("&File")
        m.addActions([self.act_add, self.act_add_folder]); m.addSeparator()
        m.addAction(self.act_save); m.addSeparator()
        m.addActions([self.act_remove, self.act_clear])
        m = self.menuBar().addMenu("&Edit")
        m.addActions([self.act_selall, self.act_selnone, self.act_revert])
        m = self.menuBar().addMenu("&Tools")
        m.addActions([self.act_comp, self.act_number, self.act_rename])

        m = self.menuBar().addMenu("&View")
        theme_menu = m.addMenu("Theme")
        group = QActionGroup(self)
        self.theme_actions = {}
        for key, label in theme.THEME_CHOICES:
            if key == "system":
                theme_menu.addSeparator()
            a = QAction(label, self, checkable=True)
            a.setChecked(key == self.theme)
            a.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            group.addAction(a); theme_menu.addAction(a)
            self.theme_actions[key] = a
        accent_menu = m.addMenu("Accent Color")
        agroup = QActionGroup(self)
        self.accent_actions = {}
        for key, label, color in theme.ACCENT_CHOICES:
            a = QAction(swatch(color), label, self, checkable=True)
            a.triggered.connect(lambda _=False, c=color: self.set_accent(c))
            agroup.addAction(a); accent_menu.addAction(a)
            self.accent_actions[color.lower()] = a
        accent_menu.addSeparator()
        self.act_custom_accent = QAction("Custom…", self, checkable=True)
        self.act_custom_accent.triggered.connect(self.pick_accent)
        agroup.addAction(self.act_custom_accent); accent_menu.addAction(self.act_custom_accent)
        self.sync_accent_checks()
        m.addSeparator()
        bigger = act("Larger Text", lambda: self.change_font(+1))
        bigger.setShortcuts([QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        smaller = act("Smaller Text", lambda: self.change_font(-1), "Ctrl+-")
        reset = act("Default Text Size", lambda: self.change_font(0, reset=True), "Ctrl+0")
        m.addActions([bigger, smaller, reset])
        m.addSeparator()
        m.addAction(act("Show / Hide Sidebar", self.toggle_sidebar, "Meta+Ctrl+S"))
        prefs = act("Preferences…", self.open_preferences, QKeySequence.Preferences)
        prefs.setMenuRole(QAction.PreferencesRole)        # macOS puts it in the TagBee menu (⌘,)
        self.file_menu.addSeparator(); self.file_menu.addAction(prefs)

        # Mp3tag-style totals on the right of the status bar
        sb = self.statusBar()
        self.stat_unsaved = QLabel(); self.stat_unsaved.setObjectName("pending")
        self.stat_sel = QLabel(); self.stat_total = QLabel()
        for l in (self.stat_unsaved, self.stat_sel, self.stat_total):
            l.setContentsMargins(10, 0, 10, 0)
            sb.addPermanentWidget(l)

    # ---- appearance (all colours come from theme.py)
    def migrate_old_settings(self):
        """First launch after the rename: carry over text size, columns and Light/Dark from TagForge."""
        if self.settings.value("migrated", False, type=bool):
            return
        old = QSettings("TagForge", "TagForge")
        for key in ("fontSize", "hiddenCols"):
            if old.contains(key) and not self.settings.contains(key):
                self.settings.setValue(key, old.value(key))
        if str(old.value("theme", "")) in ("light", "dark") and not self.settings.contains("theme"):
            self.settings.setValue("theme", str(old.value("theme")))
        self.settings.setValue("migrated", True)

    def set_theme(self, key: str):
        self.theme = key
        self.settings.setValue("theme", key)
        if key in self.theme_actions:
            self.theme_actions[key].setChecked(True)
        self.apply_theme()

    def set_accent(self, color: str):
        self.accent = QColor(color).name()
        self.settings.setValue("accent", self.accent)
        self.sync_accent_checks()
        self.apply_theme()

    def pick_accent(self):
        color = QColorDialog.getColor(QColor(self.accent), self, "Accent Color")
        if color.isValid():
            self.set_accent(color.name())
        else:
            self.sync_accent_checks()          # cancelled: tick the previous choice again

    def sync_accent_checks(self):
        preset = self.accent_actions.get(self.accent.lower())
        (preset or self.act_custom_accent).setChecked(True)

    def resolved_theme(self) -> str:
        if self.theme != "system":
            return self.theme
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Light:
            return "light"
        return "dark"

    def apply_theme(self):
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "setColorScheme"):  # Qt 6.8+: also makes the window's title bar match
            scheme = {"light": Qt.ColorScheme.Light, "system": Qt.ColorScheme.Unknown}.get(self.theme, Qt.ColorScheme.Dark)
            hints.setColorScheme(scheme)
        self.tokens = theme.Theme.make(self.resolved_theme(), self.accent)
        theme.current = self.tokens                  # FlatButton & co. paint from this
        app = QApplication.instance()
        app.setPalette(self.tokens.palette())
        app.setStyleSheet(self.tokens.stylesheet())
        for row in range(self.table.rowCount()):   # unsaved-row tint and text colours use the theme
            self.refresh_row(row)
        if hasattr(self, "logo"):
            self.apply_type_scale()
        for w in self.findChildren(FlatButton):
            w.update()

    def refresh_theme_icons(self):
        size = int(self.font_pt * 6.5)
        self.drop_area.icon.setPixmap(symbol("arrow.down.to.line", self.tokens.text_tertiary, size, self.devicePixelRatioF()))
        chevron = QIcon(symbol("chevron.down", self.tokens.accent_text, 14, self.devicePixelRatioF()))
        for a in self.menu_actions:
            a.setIcon(chevron)

    def change_font(self, delta: int, reset: bool = False):
        self.font_pt = DEFAULT_PT if reset else max(10, min(32, self.font_pt + delta))
        self.settings.setValue("fontSize", self.font_pt)
        self.apply_font()

    def apply_font(self):
        pt = self.font_pt
        f = QApplication.font()
        f.setPointSizeF(float(pt))
        QApplication.setFont(f)
        self.setFont(f)
        for w in self.findChildren(QWidget):          # make existing widgets pick up the new size
            w.setFont(f)
        self.apply_type_scale()
        scale = pt / BASE_PT
        for i, (_, _, w) in enumerate(COLUMNS):
            self.table.setColumnWidth(i, int(w * scale))
        self.table.verticalHeader().setDefaultSectionSize(int(pt * 2.3))
        self.lyrics.setFixedHeight(int(pt * 7))
        self.right.setMinimumWidth(int(pt * 20))
        self.size_cover()
        self.apply_sidebar()
        for row in range(self.table.rowCount()):   # bold flags are per-item fonts
            self.refresh_row(row)
        self.populate_art(self.panel_tracks)       # cover is drawn at the new size

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_fitted", False):
            self._fitted = True
            QTimer.singleShot(0, self.fit_height)

    def fit_height(self):
        """Open just tall enough for the whole tag panel (fields, cover, buttons) to show without scrolling."""
        self.size_cover()
        self.panel.adjustSize()
        need = self.height() - self.panel_scroll.viewport().height() + self.panel.sizeHint().height()
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            need = min(need, screen.height())
        g = self.geometry()
        g.setHeight(need)
        if screen and g.bottom() > screen.bottom():
            g.moveTop(max(screen.top(), screen.bottom() - need))
        self.setGeometry(g)

    def size_cover(self):
        """The cover fills the tag panel's width, like Mp3tag."""
        # room for the margins and the scroll bar, so the cover never pushes the panel wider than it is
        side = max(120, self.panel_scroll.width() - 20 - self.panel_scroll.verticalScrollBar().sizeHint().width())
        if self.art_label.width() != side:
            self.art_label.setFixedSize(side, side)
            self.populate_art(self.panel_tracks)

    def eventFilter(self, obj, e):
        if obj is self.panel_scroll and e.type() == QEvent.Resize:
            QTimer.singleShot(0, self.size_cover)
        return super().eventFilter(obj, e)

    def apply_type_scale(self):
        """MacBee type scale, relative to the chosen text size. Re-run after a theme change."""
        pt = self.font_pt
        f = QFont(self.font()); f.setPointSizeF(float(pt))
        def sized(scale, weight=QFont.Normal):
            g = QFont(f); g.setPointSizeF(max(9.0, round(pt * scale, 1))); g.setWeight(weight); return g
        # MacBee type scale (at 13 pt: titles 20-30 bold, body 13, details 11, labels 10 spaced capitals)
        self.panel_title.setFont(sized(0.85))
        self.brand_title.setFont(sized(1.15, QFont.Bold))
        self.drop_area.title.setFont(sized(1.85, QFont.Bold))
        self.art_info.setFont(sized(0.8)); self.drop_note.setFont(sized(0.8))
        small = sized(0.88)
        self.field_font = sized(0.82)              # tag fields and their menus: regular weight, a bit smaller
        for l in self.findChildren(QLabel):
            if l.objectName() == "taglabel":
                l.setFont(sized(0.8))
        for w in self.panel.findChildren(QWidget):
            if isinstance(w, (QLineEdit, QPlainTextEdit)):
                w.setFont(self.field_font)
            elif isinstance(w, (QCheckBox, FlatButton)):
                w.setFont(small)
        for b in (self.apply_btn, self.revert_btn, self.save_btn):
            b.setFont(small)
        eyebrow = eyebrow_font(f)
        for l in self.findChildren(QLabel):
            if l.objectName() in ("section", "fieldlabel"):
                l.setFont(eyebrow)
        self.table.horizontalHeader().setFont(eyebrow)
        self.table.horizontalHeader().viewport().setFont(eyebrow)   # headings are drawn here
        self.statusBar().setFont(sized(0.8))
        for l in (self.stat_unsaved, self.stat_sel, self.stat_total):
            l.setFont(sized(0.8, QFont.DemiBold if l is self.stat_unsaved else QFont.Normal))
        logo = int(pt * 1.75)
        ip = resource_path("icon.png")
        if ip:
            pix = QPixmap(str(ip)); pix.setDevicePixelRatio(1.0)
            pix = pix.scaled(logo * 2, logo * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation); pix.setDevicePixelRatio(2.0)
            self.logo.setPixmap(pix)
        self.refresh_theme_icons()

    # ---- loading files
    def collect_paths(self, urls: list[str]) -> list[Path]:
        found: list[Path] = []
        for u in urls:
            p = Path(u)
            if p.is_dir():
                for root, dirs, files in os.walk(p):
                    dirs.sort(key=natural_key)
                    for name in sorted(files, key=natural_key):
                        if Path(name).suffix.lower() in tagio.SUPPORTED_EXTS and not name.startswith("._"):
                            found.append(Path(root) / name)
            elif p.suffix.lower() in tagio.SUPPORTED_EXTS:
                found.append(p)
        have = {t.path.resolve() for t in self.tracks.values()}
        out, seen = [], set()
        for p in found:
            r = p.resolve()
            if r not in have and r not in seen:
                seen.add(r); out.append(p)
        return out

    def add_paths(self, urls: list[str]):
        paths = self.collect_paths(urls)
        if not paths:
            self.statusBar().showMessage("No new supported audio files found.", 4000)
            return
        errors = []
        progress = None
        if len(paths) > 3:
            progress = QProgressDialog("Loading files…", "Cancel", 0, len(paths), self)
            progress.setWindowTitle(APP_NAME)
            progress.setWindowModality(Qt.WindowModal); progress.setMinimumDuration(200)
        added = []
        for i, p in enumerate(paths):
            if progress:
                progress.setLabelText(f"Loading files…\n{i + 1} of {len(paths)}")
                progress.setValue(i)
                if progress.wasCanceled():
                    break
            try:
                t = Track(p)
                t.size = p.stat().st_size
            except Exception as exc:
                errors.append(f"{p.name}: {exc}")
                continue
            uid = self._next_uid; self._next_uid += 1
            self.tracks[uid] = t
            added.append(uid)
        if progress:
            progress.setValue(len(paths))
        self.table.setSortingEnabled(False)
        for uid in added:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for c in range(len(COLUMNS)):
                it = SortItem()
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == 0:
                    it.setData(Qt.UserRole, uid)
                self.table.setItem(row, c, it)
            self.refresh_row(row)
        self.stack.setCurrentIndex(1 if self.tracks else 0)
        if self._sort_col is not None:
            self.table.sortItems(self._sort_col, self._sort_order)
        if errors:
            QMessageBox.warning(self, APP_NAME, "Some files couldn't be read:\n\n" + "\n".join(errors[:15]))
        self.update_status()
        n = len(added)
        self.statusBar().showMessage(f"Added {n} file{'s' if n != 1 else ''}.", 5000)

    def add_files_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(tagio.SUPPORTED_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Add audio files", "", f"Audio files ({exts})")
        if files:
            self.add_paths(files)

    def add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder")
        if d:
            self.add_paths([d])

    # ---- drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.set_drag_highlight(True)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.set_drag_highlight(False)

    def set_drag_highlight(self, on: bool):
        for w in (self.stack, self.drop_area):
            self.mark(w, "drag" if on else "")

    def dropEvent(self, e):
        self.set_drag_highlight(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        images = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXTS]
        audio = [p for p in paths if p not in images]
        if images and not audio:
            if self.selected_tracks():
                self.set_cover_from_file(images[0])
            else:
                self.statusBar().showMessage("Select the tracks first, then drop the image.", 5000)
        else:
            self.add_paths(audio)
        e.acceptProposedAction()

    # ---- table <-> tracks
    def track_at(self, row: int) -> Track:
        return self.tracks[self.table.item(row, 0).data(Qt.UserRole)]

    def selected_tracks(self) -> list[Track]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.track_at(r) for r in rows]

    def refresh_row(self, row: int):
        t = self.track_at(row)
        changed = t.changed_fields()
        dirty = t.is_dirty()
        for c, (key, _, _) in enumerate(COLUMNS):
            if key == "file":
                text, sk = t.path.name, natural_key(t.path.name)
            elif key == "format":
                text = sk = t.quality
            elif key == "length":
                text, sk = fmt_time(t.length), t.length
            elif key == "compilation":
                text = "✓" if t.tags["compilation"] else ""
                sk = text
            elif key == "track":
                text = t.tags["track"]
                sk = int(text) if text.isdigit() else 0
            else:
                text = t.tags[key]
                sk = text.lower()
            it = self.table.item(row, c)
            it.setText(text)
            it.setData(Qt.UserRole + 1, sk)
            font = QFont(self.table.font()); font.setBold(dirty and (key in changed or key == "file")); it.setFont(font)
            it.setBackground(self.tokens.pending_row() if dirty else QColor(0, 0, 0, 0))
            if key == "compilation":
                it.setForeground(self.tokens.accent_text)
            elif key == "track":
                it.setForeground(self.tokens.text_tertiary)
            elif key in SECONDARY_COLUMNS:
                it.setForeground(self.tokens.text_secondary)
            if key == "format":
                it.setData(Qt.UserRole + 2, t.is_hires)
            if key == "compilation":
                it.setTextAlignment(Qt.AlignCenter)

    def refresh_tracks(self, tracks):
        wanted = {id(t) for t in tracks}
        for row in range(self.table.rowCount()):
            if id(self.track_at(row)) in wanted:
                self.refresh_row(row)

    def on_header_clicked(self, col: int):
        if self._sort_col == col:
            self._sort_order = Qt.DescendingOrder if self._sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self._sort_col, self._sort_order = col, Qt.AscendingOrder
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSortIndicator(col, self._sort_order)
        self.table.sortItems(col, self._sort_order)

    # ---- sidebar
    def set_sidebar_width(self, w: int):
        self.sidebar_width = int(w)
        self.settings.setValue("sidebarWidth", self.sidebar_width)
        self.apply_sidebar()

    def open_preferences(self):
        PreferencesDialog(self).exec()

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.settings.setValue("sidebarCollapsed", self.sidebar_collapsed)
        self.apply_sidebar()

    def apply_sidebar(self):
        """Full sidebar, or a narrow rail of icons (hover for names)."""
        c = self.sidebar_collapsed
        self.logo.setVisible(not c); self.brand_title.setVisible(not c)
        self.brand_row.setContentsMargins(0 if c else 10, 0, 0, 0)
        for b, text in self.sidebar_rows:
            b.setText("" if c else text)
        for l in self.sidebar_sections:
            l.setVisible(not c)
        pt = self.font_pt
        if c:
            w = self.sidebar_rows[0][0].sizeHint().width() + 16
            self.sidebar.setMinimumWidth(w); self.sidebar.setMaximumWidth(w)
        else:
            self.sidebar.setMinimumWidth(self.sidebar_width); self.sidebar.setMaximumWidth(self.sidebar_width)
        left = self.sidebar.minimumWidth()
        right = int(pt * 23)
        self.split.setSizes([left, max(300, self.width() - left - right), right])

    # ---- tag panel: edits go straight onto the selected tracks; Save writes them
    @staticmethod
    def mark(w, state: str):
        w.setProperty("state", state)
        w.style().unpolish(w); w.style().polish(w); w.update()

    def has_draft(self) -> bool:
        return bool(self.draft) or self.draft_art is not None

    def on_selection_changed(self):
        # edits you didn't Apply are kept: they go onto the tracks you were editing (still not written)
        self.apply_draft(repopulate=False)
        self.populate_panel(self.selected_tracks())
        self.update_status()

    def populate_panel(self, tracks: list[Track]):
        self._populating = True
        try:
            self.panel_tracks = list(tracks)
            self.panel_orig = {k: [t.tags[k] for t in tracks] for k in self.widgets}   # for "< keep >"
            self.panel.setEnabled(bool(tracks))
            self.draft, self.draft_art = {}, None
            if not tracks:
                self.panel_title.setText("Select tracks to edit their tags")
            elif len(tracks) == 1:
                self.panel_title.setText(tracks[0].path.name)
            else:
                self.panel_title.setText(f"{len(tracks)} tracks selected · < keep > = they differ")
            for key in self.widgets:
                self.show_field(key)
            self.populate_art(tracks)
        finally:
            self._populating = False
        self.update_buttons()

    def show_field(self, key: str):
        """Show a field's current value, or < keep > when the selected tracks differ."""
        w = self.widgets[key]
        vals = {t.tags[key] for t in self.panel_tracks}
        mixed = len(vals) > 1
        value = "" if (mixed or not vals) else next(iter(vals))
        was = self._populating
        self._populating = True
        try:
            if key == "compilation":
                w.set_state(None if (mixed or not self.panel_tracks) else ("1" if value else ""),
                            show_label=bool(self.panel_tracks))
                return
            if key == "lyrics":
                w.setPlainText(value)
            else:
                w.setText(value)
            w.setPlaceholderText(MIXED_HINT if mixed else "")
            self.mark(w, "mixed" if mixed else "")
        finally:
            self._populating = was

    def value_menu(self, key: str):
        """Mp3tag's field dropdown: < keep >, < blank >, or one of the values the selected tracks have."""
        if not self.panel_tracks:
            return
        w = self.widgets[key]
        menu = QMenu(self); menu.setFont(self.field_font)
        orig = self.panel_orig.get(key, [])
        if len(set(orig)) > 1:
            menu.addAction(MIXED_HINT, lambda: self.restore_field(key))
        menu.addAction(CLEARED_HINT, lambda: self.clear_field(key))
        values = sorted({v for v in orig if v} | {t.tags[key] for t in self.panel_tracks if t.tags[key]},
                        key=natural_key)
        if values:
            menu.addSeparator()
            for v in values[:40]:
                menu.addAction(v.replace("&", "&&"), lambda v=v: self.set_field(key, v))
        menu.exec(w.mapToGlobal(w.rect().bottomLeft()))

    def set_field(self, key: str, value: str):
        w = self.widgets[key]
        self._populating = True
        try:
            w.setText(value)
        finally:
            self._populating = False
        self.on_field_edited(key, value)

    def restore_field(self, key: str):
        """< keep >: drop the edit, so each track keeps its own value."""
        self.draft.pop(key, None)
        self.show_field(key)
        self.update_buttons()

    def populate_art(self, tracks: list[Track]):
        self.art_label.setPixmap(QPixmap())
        if not tracks:
            self.art_label.setText(""); self.art_info.setText(""); return
        if self.draft_art is not None:
            if self.draft_art[0] == "remove":
                self.art_label.setText("Will be removed")
                self.art_info.setText("not applied yet")
            else:
                self.show_pixmap(self.draft_art[2], "not applied yet")
            return
        if all(t.art_op is not None for t in tracks) and len({t.art_digest() for t in tracks}) == 1:
            if tracks[0].art_op[0] == "remove":
                self.art_label.setText("Will be\nremoved")
                self.art_info.setText("unsaved")
                return
            self.show_pixmap(tracks[0].art_op[2], "unsaved")
            return
        digests = {t.art_digest() for t in tracks}
        if len(digests) > 1:
            self.art_label.setText("Different\ncovers")
            self.art_info.setText("")
            return
        art = tracks[0].read_art()
        if not art:
            self.art_label.setText("No cover")
            self.art_info.setText("")
            return
        self.show_pixmap(art[1], f"{art[0].split('/')[-1].upper()} · {len(art[1]) // 1024} KB")

    def show_pixmap(self, data: bytes, note: str):
        pix = QPixmap()
        if pix.loadFromData(data):
            side = self.art_label.width()
            self.art_label.setPixmap(rounded(pix, side, self.devicePixelRatioF()))
            self.art_info.setText(f"{pix.width()}×{pix.height()} · {note}")
        else:
            self.art_label.setText("Unreadable cover")

    def on_field_edited(self, key: str, value: str):
        if self._populating or not self.panel_tracks:
            return
        self.draft[key] = value
        if key != "compilation":
            w = self.widgets[key]
            self.mark(w, "cleared" if value == "" else "edited")
            if value == "":
                w.setPlaceholderText(CLEARED_HINT)
        self.update_buttons()

    def on_lyrics_changed(self):
        if not self._populating:
            self.on_field_edited("lyrics", self.lyrics.toPlainText())

    def clear_field(self, key: str):
        if not self.panel_tracks:
            return
        w = self.widgets[key]
        self._populating = True
        try:
            w.setPlainText("") if key == "lyrics" else w.setText("")
        finally:
            self._populating = False
        self.on_field_edited(key, "")

    def apply_draft(self, repopulate: bool = True):
        """Apply: put the drafted edits on the tracks shown in the panel (files aren't written yet)."""
        tracks = self.panel_tracks
        if not tracks or not self.has_draft():
            return
        for t in tracks:
            for k, v in self.draft.items():
                t.tags[k] = v
            if self.draft_art is not None:
                t.set_art(self.draft_art[1], self.draft_art[2]) if self.draft_art[0] == "set" else t.remove_art()
        self.draft, self.draft_art = {}, None
        self.refresh_tracks(tracks)
        if repopulate:
            self.populate_panel(tracks)
        self.update_status()

    def revert(self):
        """Revert: throw away edits not applied yet; with none, undo the selected tracks' unsaved changes."""
        if self.has_draft():
            self.populate_panel(self.panel_tracks)
            self.update_status()
        else:
            self.revert_selected()

    def update_buttons(self):
        draft = self.has_draft()
        n = len(self.dirty_tracks())
        self.apply_btn.setEnabled(draft)
        self.revert_btn.setEnabled(draft or any(t.is_dirty() for t in self.panel_tracks))
        self.save_btn.setEnabled(draft or bool(n))

    def after_change(self, tracks):
        self.refresh_tracks(tracks)
        self.update_status()
        self.update_buttons()

    # ---- cover art (applied to the selected tracks right away, written on Save)
    def choose_cover(self):
        if not self.panel_tracks:
            return
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        path, _ = QFileDialog.getOpenFileName(self, "Choose cover image", "", f"Images ({exts})")
        if path:
            self.set_cover_from_file(path)

    def set_cover_from_file(self, path: str):
        if not self.panel_tracks:
            return
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Couldn't read the image:\n{exc}")
            return
        img = QImage.fromData(raw)
        if img.isNull():
            QMessageBox.warning(self, APP_NAME, "That file isn't a readable image.")
            return
        if raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff":
            mime = tagio.sniff_mime(raw)
        else:  # convert webp/bmp/gif/tiff to JPEG so every player can show it
            buf = QBuffer(); buf.open(QIODevice.WriteOnly)
            img.convertToFormat(QImage.Format_RGB32).save(buf, "JPEG", 92)
            raw, mime = bytes(buf.data()), "image/jpeg"
        self.draft_art = ("set", mime, raw)
        self.populate_art(self.panel_tracks)
        self.update_buttons()

    def cover_menu(self, pos):
        if not self.panel_tracks:
            return
        menu = QMenu(self)
        menu.addAction("Replace Cover…", self.choose_cover)
        menu.addAction("Remove Cover", self.remove_cover)
        menu.exec(self.art_label.mapToGlobal(pos))

    def remove_cover(self):
        if not self.panel_tracks:
            return
        self.draft_art = ("remove",)
        self.populate_art(self.panel_tracks)
        self.update_buttons()

    # ---- tools
    def need_selection(self) -> list[Track]:
        self.apply_draft()
        tracks = self.selected_tracks()
        if not tracks:
            QMessageBox.information(self, APP_NAME, "Select the tracks first (⌘A selects everything).")
        return tracks

    def make_compilation(self):
        tracks = self.need_selection()
        if not tracks:
            return
        albums = {t.tags["album"] for t in tracks}
        dlg = CompilationDialog(self, next(iter(albums)) if len(albums) == 1 else "")
        if dlg.exec() != QDialog.Accepted:
            return
        aa, album = dlg.album_artist.text().strip(), dlg.album.text().strip()
        for i, t in enumerate(tracks, 1):
            t.tags["albumartist"] = aa
            t.tags["compilation"] = "1"
            if album:
                t.tags["album"] = album
            if dlg.number.isChecked():
                t.tags["track"], t.tags["tracktotal"] = str(i), str(len(tracks))
        self.populate_panel(tracks)
        self.after_change(tracks)
        self.statusBar().showMessage(f"Compilation set on {len(tracks)} tracks — press ⌘S to write the files.", 6000)

    def auto_number(self):
        tracks = self.need_selection()
        if not tracks:
            return
        dlg = AutoNumberDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        start = dlg.start.value()
        for i, t in enumerate(tracks):
            t.tags["track"] = str(start + i)
            if dlg.total.isChecked():
                t.tags["tracktotal"] = str(len(tracks))
            if dlg.disc.text().strip():
                t.tags["disc"] = dlg.disc.text().strip()
        self.populate_panel(tracks)
        self.after_change(tracks)

    def rename_files(self):
        tracks = self.need_selection()
        if not tracks:
            return
        dlg = RenameDialog(self, tracks)
        if dlg.exec() != QDialog.Accepted:
            return
        errors = []
        for t in tracks:
            try:
                tagio.rename_track(t, dlg.new_stem(t))
            except OSError as exc:
                errors.append(f"{t.path.name}: {exc}")
        self.refresh_tracks(tracks)
        self.populate_panel(tracks)
        if errors:
            QMessageBox.warning(self, APP_NAME, "Some files couldn't be renamed:\n\n" + "\n".join(errors))

    # ---- save / revert / remove
    def dirty_tracks(self) -> list[Track]:
        return [t for t in self.tracks.values() if t.is_dirty()]

    def save_all(self) -> bool:
        self.apply_draft()
        dirty = self.dirty_tracks()
        if not dirty:
            return True
        errors = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for t in dirty:
                try:
                    t.save()
                    t.size = t.path.stat().st_size
                except Exception as exc:
                    errors.append(f"{t.path.name}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        for row in range(self.table.rowCount()):
            self.refresh_row(row)
        self.populate_panel(self.selected_tracks())
        self.update_status()
        self.update_buttons()
        if errors:
            QMessageBox.critical(self, APP_NAME, "These files could not be saved (unsaved changes were kept):\n\n"
                                 + "\n".join(errors[:15]))
            return False
        self.statusBar().showMessage(f"Saved {len(dirty)} file(s).", 4000)
        return True

    def revert_selected(self):
        tracks = self.selected_tracks()
        for t in tracks:
            t.revert()
        self.populate_panel(tracks)
        self.after_change(tracks)

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        self.draft, self.draft_art = {}, None
        if any(self.track_at(r).is_dirty() for r in rows):
            if QMessageBox.question(self, APP_NAME, "Some of these tracks have unsaved changes. Remove them anyway?") != QMessageBox.Yes:
                return
        for r in rows:
            del self.tracks[self.table.item(r, 0).data(Qt.UserRole)]
            self.table.removeRow(r)
        self.stack.setCurrentIndex(1 if self.tracks else 0)
        self.populate_panel(self.selected_tracks())
        self.update_status()

    def clear_list(self):
        self.table.selectAll()
        self.remove_selected()

    # ---- status / lifecycle
    def update_status(self):
        """Mp3tag-style totals: count (time | size) for the selection and for the whole list."""
        def summary(tracks):
            secs = sum(t.length for t in tracks)
            size = sum(getattr(t, "size", 0) for t in tracks)
            return f"{len(tracks)} ({fmt_duration(secs)} | {fmt_size(size)})"
        sel, dirty = self.selected_tracks(), len(self.dirty_tracks())
        self.stat_unsaved.setText(f"● {dirty} unsaved" if dirty else "")
        self.stat_sel.setText(f"Selected: {summary(sel)}" if sel else "")
        self.stat_total.setText(f"Total: {summary(list(self.tracks.values()))}")
        self.setWindowTitle(f"{APP_NAME}{' — ' + str(dirty) + ' unsaved' if dirty else ''}")
        self.act_save.setEnabled(bool(dirty) or self.has_draft())

    def closeEvent(self, e):
        if self.dirty_tracks() or self.has_draft():
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText("You have changes that haven't been written to your files.")
            box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            box.setDefaultButton(QMessageBox.Save)
            r = box.exec()
            if r == QMessageBox.Cancel or (r == QMessageBox.Save and not self.save_all()):
                e.ignore()
                return
        self.settings.setValue("windowGeometry", self.saveGeometry())
        e.accept()


class TagBeeApp(QApplication):
    """Also receives files dropped on the Dock icon / opened with 'Open With' (macOS)."""

    def __init__(self, argv):
        super().__init__(argv)
        self.win = None
        self._pending = []
        self._flush = QTimer(self, singleShot=True, interval=200)
        self._flush.timeout.connect(self._deliver)

    def event(self, e):
        if e.type() == QEvent.FileOpen:
            self._pending.append(e.file())
            self._flush.start()      # batch several dropped files into one load
            return True
        return super().event(e)

    def _deliver(self):
        if self.win is not None and self._pending:
            paths, self._pending = self._pending, []
            self.win.add_paths(paths)
            self.win.raise_(); self.win.activateWindow()


def main():
    app = TagBeeApp(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")      # draws every control from our theme colours (the native Mac style ignores some)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for cand in (base / "icon.png", base.parent / "Resources" / "icon.png"):
        if cand.exists():
            app.setWindowIcon(QIcon(str(cand)))   # also sets the Dock icon on macOS
            break
    win = MainWindow()
    app.win = win
    win.show()
    args = [a for a in sys.argv[1:] if not a.startswith("-psn")]
    if args:
        win.add_paths(args)
    app._deliver()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
