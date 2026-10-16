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
from PySide6.QtCore import QBuffer, QByteArray, QEasingCurve, QEvent, QIODevice, QSettings, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QFont, QGuiApplication, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGraphicsDropShadowEffect, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressDialog,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

import tagio
import theme
from tagio import Track

APP_NAME = "TagBee"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
MULTI = "‹multiple values›"
MIXED_HINT = "Multiple values"
CLEARED_HINT = "(will be cleared)"
BASE_PT = 13          # column widths below are designed for this text size
DEFAULT_PT = 16

# table column key, header, default width
COLUMNS = [
    ("file", "File", 150), ("track", "#", 38), ("title", "Title", 150),
    ("artist", "Artist", 120), ("album", "Album", 130), ("albumartist", "Album Artist", 110),
    ("date", "Year", 50), ("genre", "Genre", 80), ("compilation", "Comp.", 56),
    ("format", "Format", 56), ("length", "Time", 46),
]


def resource_path(name: str):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for cand in (base / name, base.parent / "Resources" / name):
        if cand.exists():
            return cand
    return None


class ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, e):
        self.clicked.emit()


def natural_key(s: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def fmt_time(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class RowHoverDelegate(QStyledItemDelegate):
    """Highlights the whole row under the mouse, like MacBee's track rows."""

    def __init__(self, table: QTableWidget, color):
        super().__init__(table)
        self.table, self.color, self.row = table, color, -1      # color: callable returning a QColor
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
        if index.row() == self.row and not option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, self.color())
        tint = index.data(Qt.BackgroundRole)      # the stylesheet hides item backgrounds, so paint the unsaved tint here
        if tint is not None and tint.color().alpha():
            painter.fillRect(option.rect, tint)
        super().paint(painter, option, index)


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
        lay.addWidget(QLabel(
            "Pattern - use %track% %disc% %title% %artist% %album% %albumartist% %date% %genre% …"
        ))
        self.pattern = QLineEdit("%track% - %artist% - %title%")
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


class CompilationToggle(QWidget):
    """Two big Yes / No buttons. Neither lit = the selected tracks differ."""
    chosen = Signal(str)          # "1" or ""

    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.yes = QPushButton("Yes"); self.no = QPushButton("No")
        self.mixed = QLabel(MULTI); self.mixed.setObjectName("muted")
        for b in (self.yes, self.no):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
        self.yes.clicked.connect(lambda: self._pick("1"))
        self.no.clicked.connect(lambda: self._pick(""))
        row.addWidget(self.yes); row.addWidget(self.no); row.addWidget(self.mixed); row.addStretch(1)
        self.set_state(None)

    def _pick(self, value):
        self.set_state(value)
        self.chosen.emit(value)

    def set_state(self, value, show_label=True):
        """value: "1", "" or None (mixed / nothing selected)."""
        self.yes.setChecked(value == "1")
        self.no.setChecked(value == "")
        self.mixed.setVisible(value is None and show_label)


# --------------------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        self.resize(int(avail.width() * 0.92), int(avail.height() * 0.92)) if avail else self.resize(1440, 820)
        self.setAcceptDrops(True)
        self.tracks: dict[int, Track] = {}
        self._next_uid = 0
        self._populating = False
        self._sort_col, self._sort_order = None, Qt.AscendingOrder
        self.panel_tracks: list[Track] = []      # tracks currently shown in the editor panel
        self.draft: dict[str, str] = {}          # edits typed but not yet applied
        self.draft_art = None                     # cover change not yet applied

        self.settings = QSettings("TagBee", "TagBee")
        self.migrate_old_settings()
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
        self.apply_theme()
        self.apply_font()
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self.theme == "system" and self.apply_theme())
        self.populate_panel([])
        self.update_status()

    # ---- UI construction: sidebar | track list | inspector
    def _build_ui(self):
        # ===== left sidebar: drop zone, add, tools
        self.sidebar = QWidget(); self.sidebar.setObjectName("sidebar")
        self.sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sb = QVBoxLayout(self.sidebar); sb.setContentsMargins(14, 14, 14, 14); sb.setSpacing(8)

        brand = QHBoxLayout(); brand.setSpacing(10)
        logo = QLabel(); logo.setFixedSize(40, 40)
        ip = resource_path("icon.png")
        if ip:
            logo.setPixmap(QPixmap(str(ip)).scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        names = QVBoxLayout(); names.setSpacing(0)
        self.brand_title = QLabel(APP_NAME); self.brand_title.setObjectName("brand")
        sub = QLabel("Music tag editor"); sub.setObjectName("muted")
        names.addWidget(self.brand_title); names.addWidget(sub)
        brand.addWidget(logo); brand.addLayout(names, 1)
        sb.addLayout(brand)
        sb.addSpacing(6)

        self.drop_zone = ClickLabel("Drop music files\nor folders here\n\nFLAC · M4A · MP3\nOGG · OPUS\nWAV · AIFF")
        self.drop_zone.setObjectName("dropzone"); self.drop_zone.setAlignment(Qt.AlignCenter)
        self.drop_zone.setCursor(Qt.PointingHandCursor)
        self.drop_zone.setToolTip("Drop files here, or click to choose files")
        self.drop_zone.clicked.connect(self.add_files_dialog)
        self.drop_zone.setMinimumHeight(150)
        sb.addWidget(self.drop_zone, 1)

        def sbutton(text, slot, primary=False, tip=None):
            b = QPushButton(text)
            if primary:
                b.setObjectName("primary")
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        sb.addWidget(sbutton("Add Files…", self.add_files_dialog, True))
        sb.addWidget(sbutton("Add Folder…", self.add_folder_dialog))

        def section(text):
            l = QLabel(text); l.setObjectName("section"); return l

        sb.addSpacing(6); sb.addWidget(section("TOOLS"))
        sb.addWidget(sbutton("Make Compilation…", self.make_compilation, tip="Set Album Artist + Compilation flag, keep each track's artist (⌘K)"))
        sb.addWidget(sbutton("Auto-number…", self.auto_number, tip="Number the selected tracks in list order"))
        sb.addWidget(sbutton("Rename Files…", self.rename_files, tip="Rename files from their tags"))
        sb.addSpacing(6); sb.addWidget(section("LIST"))
        sb.addWidget(sbutton("Remove selected", self.remove_selected, tip="Remove from this window only (files aren't touched)"))
        sb.addWidget(sbutton("Clear list", self.clear_list))
        sb.addStretch(0)

        # ===== middle: track list (with an empty-state hint)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setItemDelegate(RowHoverDelegate(self.table, lambda: self.tokens.surface))
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

        hint = QLabel("Your tracks will appear here")
        hint.setAlignment(Qt.AlignCenter)
        hint.setObjectName("emptyhint")
        self.empty_hint = hint
        self.stack = QStackedWidget()
        self.stack.addWidget(hint)
        self.stack.addWidget(self.table)

        # ===== right: inspector (compact header + two-column tag grid)
        self.panel_title = QLabel()
        self.panel_title.setWordWrap(True)
        self.panel_hint = QLabel(); self.panel_hint.setWordWrap(True); self.panel_hint.setObjectName("muted")
        self.art_label = CoverLabel()
        self.art_label.setFixedSize(130, 130)
        self.art_label.setAlignment(Qt.AlignCenter)
        self.art_label.setWordWrap(True)
        self.art_label.setToolTip("Drop an image anywhere on the window to set the cover")
        self.art_info = QLabel(); self.art_info.setObjectName("muted"); self.art_info.setWordWrap(True)
        replace_btn = QPushButton("Replace…"); replace_btn.clicked.connect(self.choose_cover)
        remove_btn = QPushButton("Remove"); remove_btn.clicked.connect(self.remove_cover)
        art_buttons = QHBoxLayout(); art_buttons.setSpacing(6)
        art_buttons.addWidget(replace_btn); art_buttons.addWidget(remove_btn)
        head_text = QVBoxLayout(); head_text.setSpacing(3)
        head_text.addWidget(self.panel_title); head_text.addWidget(self.panel_hint)
        head_text.addWidget(self.art_info); head_text.addLayout(art_buttons); head_text.addStretch(1)
        header = QHBoxLayout(); header.setSpacing(12)
        header.addWidget(self.art_label, 0, Qt.AlignTop); header.addLayout(head_text, 1)

        self.widgets: dict[str, QWidget] = {}
        self.clear_buttons = {}

        def with_clear(key, editor, top=False):
            box = QWidget()
            h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
            h.addWidget(editor, 1)
            btn = QToolButton(); btn.setText("✕"); btn.setObjectName("clearbtn")
            btn.setToolTip("Clear this field on every selected track")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.clear_field(k))
            h.addWidget(btn, 0, Qt.AlignTop if top else Qt.AlignVCenter)
            self.clear_buttons[key] = btn
            return box

        def line(key):
            w = QLineEdit()
            w.textEdited.connect(lambda text, k=key: self.on_field_edited(k, text))
            self.widgets[key] = w
            return with_clear(key, w)

        self.comp_combo = CompilationToggle()
        self.comp_combo.chosen.connect(lambda v: self.on_field_edited("compilation", v))
        self.widgets["compilation"] = self.comp_combo

        self.lyrics = QPlainTextEdit()
        self.lyrics.setFixedHeight(90)
        self.lyrics.textChanged.connect(self.on_lyrics_changed)
        self.widgets["lyrics"] = self.lyrics

        grid = QGridLayout(); grid.setHorizontalSpacing(10); grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)

        def add(row, col, label, widget, span=1):
            cell = QWidget()
            v = QVBoxLayout(cell); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
            lab = QLabel(label); lab.setObjectName("fieldlabel")
            v.addWidget(lab); v.addWidget(widget)
            grid.addWidget(cell, row, col, 1, span)

        add(0, 0, "Title", line("title"));            add(0, 1, "Artist", line("artist"))
        add(1, 0, "Album", line("album"));            add(1, 1, "Album Artist", line("albumartist"))
        add(2, 0, "Compilation", self.comp_combo);    add(2, 1, "Year / Date", line("date"))
        add(3, 0, "Genre", line("genre"));            add(3, 1, "Composer", line("composer"))
        add(4, 0, "Track", line("track"));            add(4, 1, "Total tracks", line("tracktotal"))
        add(5, 0, "Disc", line("disc"));              add(5, 1, "Total discs", line("disctotal"))
        add(6, 0, "BPM", line("bpm"));                add(6, 1, "Grouping", line("grouping"))
        add(7, 0, "Copyright", line("copyright"));    add(7, 1, "Comment", line("comment"))
        add(8, 0, "Lyrics", with_clear("lyrics", self.lyrics, top=True), span=2)

        sort_box = QGroupBox("Sort names (optional)")
        sort_box.setCheckable(True); sort_box.setChecked(False)
        sort_form = QFormLayout(sort_box)
        for key in ("titlesort", "artistsort", "albumsort", "albumartistsort"):
            sort_form.addRow(tagio.LABELS[key], line(key))
        sort_inner = [sort_form.itemAt(i).widget() for i in range(sort_form.count())]
        sort_box.toggled.connect(lambda on: [w.setVisible(on) for w in sort_inner if w])
        sort_box.toggled.emit(False)

        panel_layout = QVBoxLayout(); panel_layout.setContentsMargins(12, 12, 12, 6); panel_layout.setSpacing(10)
        panel_layout.addLayout(header)
        panel_layout.addLayout(grid)
        panel_layout.addWidget(sort_box)
        panel_layout.addStretch(1)
        self.panel = QWidget(); self.panel.setLayout(panel_layout); self.panel.setObjectName("inspectorPanel")
        scroll = QScrollArea(); scroll.setWidget(self.panel); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.apply_btn = QPushButton("Apply"); self.apply_btn.setObjectName("primary")
        self.apply_btn.setShortcut("Ctrl+Return")
        self.apply_btn.setToolTip("Stage your edits on the selected tracks (⌘↩). Nothing is written to the files yet.")
        self.apply_btn.clicked.connect(self.apply_draft)
        self.discard_btn = QPushButton("Discard edits"); self.discard_btn.clicked.connect(self.discard_draft)
        self.save_btn = QPushButton("Save to files"); self.save_btn.clicked.connect(self.save_all)
        self.save_btn.setToolTip("Apply any pending edits and write every changed track into its file (⌘S)")
        self.pending_label = QLabel(); self.pending_label.setObjectName("pending")
        bar = QVBoxLayout(); bar.setContentsMargins(12, 6, 12, 10)
        bar.addWidget(self.pending_label)
        bar.addWidget(self.apply_btn)
        row = QHBoxLayout(); row.addWidget(self.discard_btn); row.addWidget(self.save_btn)
        bar.addLayout(row)
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
        self.act_save = act("Save", self.save_all, QKeySequence.Save, "Write all changes into the original files")
        self.act_revert = act("Revert Selected", self.revert_selected, "Ctrl+R", "Discard unsaved changes on the selected tracks")
        self.act_remove = act("Remove from List", self.remove_selected, QKeySequence.Delete, "Remove from this window (files aren't touched)")
        self.act_clear = act("Clear List", self.clear_list)
        self.act_comp = act("Make Compilation…", self.make_compilation, "Ctrl+K", "Set Album Artist + Compilation flag, keep track artists")
        self.act_number = act("Auto-number…", self.auto_number, None, "Number the selected tracks in list order")
        self.act_rename = act("Rename Files…", self.rename_files, None, "Rename files from their tags")
        self.act_selall = act("Select All", lambda: self.table.selectAll(), QKeySequence.SelectAll)

        m = self.menuBar().addMenu("&File")
        m.addActions([self.act_add, self.act_add_folder]); m.addSeparator()
        m.addAction(self.act_save); m.addSeparator()
        m.addActions([self.act_remove, self.act_clear])
        m = self.menuBar().addMenu("&Edit")
        m.addActions([self.act_selall, self.act_revert])
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

        self.statusBar()

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
        app = QApplication.instance()
        app.setPalette(self.tokens.palette())
        app.setStyleSheet(self.tokens.stylesheet())
        for row in range(self.table.rowCount()):   # unsaved-row tint uses the theme
            self.refresh_row(row)

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
        bold = QFont(f); bold.setBold(True)
        self.panel_title.setFont(bold)
        small = QFont(f); small.setPointSizeF(max(9.0, pt - 2))
        self.art_info.setFont(small); self.panel_hint.setFont(small); self.drop_zone.setFont(small)
        brand = QFont(f); brand.setBold(True); brand.setPointSizeF(pt + 3); self.brand_title.setFont(brand)
        sec = QFont(f); sec.setBold(True); sec.setPointSizeF(max(9.0, pt - 4)); [l.setFont(sec) for l in self.sidebar.findChildren(QLabel) if l.objectName() == "section"]
        big = QFont(f); big.setPointSizeF(pt + 3)
        self.empty_hint.setFont(big)
        scale = pt / BASE_PT
        for i, (_, _, w) in enumerate(COLUMNS):
            self.table.setColumnWidth(i, int(w * scale))
        self.table.verticalHeader().setDefaultSectionSize(int(pt * 2.1))
        self.lyrics.setFixedHeight(int(pt * 7))
        art = int(pt * 8.2)
        self.art_label.setFixedSize(art, art)
        self.sidebar.setMinimumWidth(int(pt * 14)); self.right.setMinimumWidth(int(pt * 26))
        self.statusBar().setFont(f)
        left, right = int(pt * 15.5), int(pt * 29)
        self.split.setSizes([left, max(300, self.width() - left - right), right])
        for row in range(self.table.rowCount()):   # bold flags are per-item fonts
            self.refresh_row(row)

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
        if len(paths) > 25:
            progress = QProgressDialog("Reading tags…", "Cancel", 0, len(paths), self)
            progress.setWindowModality(Qt.WindowModal); progress.setMinimumDuration(300)
        added = []
        for i, p in enumerate(paths):
            if progress:
                progress.setValue(i)
                if progress.wasCanceled():
                    break
            try:
                t = Track(p)
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

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
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
                text = sk = t.format
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

    # ---- editor panel: edits are drafted here and only staged when you click Apply
    def has_draft(self) -> bool:
        return bool(self.draft) or self.draft_art is not None

    @staticmethod
    def mark(w, state: str):
        w.setProperty("state", state)
        w.style().unpolish(w); w.style().polish(w); w.update()

    def on_selection_changed(self):
        if self.has_draft():
            n = len(self.panel_tracks)
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText(f"You have edits that haven't been applied to the {n} track{'s' if n != 1 else ''} you were editing.")
            box.setInformativeText("Apply them now? (Applying doesn't write to the files - Save does that.)")
            apply_b = box.addButton("Apply", QMessageBox.AcceptRole)
            box.addButton("Discard", QMessageBox.DestructiveRole)
            box.setDefaultButton(apply_b)
            box.exec()
            if box.clickedButton() is apply_b:
                self.apply_draft()
            self.draft, self.draft_art = {}, None
        self.populate_panel(self.selected_tracks())

    def populate_panel(self, tracks: list[Track]):
        self._populating = True
        try:
            self.panel_tracks = list(tracks)
            self.draft, self.draft_art = {}, None
            self.panel.setEnabled(bool(tracks))
            for b in self.clear_buttons.values():
                b.setEnabled(bool(tracks))
            self.panel_hint.setText("")
            if not tracks:
                self.panel_title.setText("Select one or more tracks to edit")
            elif len(tracks) == 1:
                self.panel_title.setText(tracks[0].path.name)
                self.panel_hint.setText("Edit, then Apply. Nothing is written until you Save.")
            else:
                self.panel_title.setText(f"{len(tracks)} tracks selected")
                self.panel_hint.setText("Orange dashed = values differ. Type to replace all, ✕ clears.")
            for key, w in self.widgets.items():
                vals = {t.tags[key] for t in tracks}
                mixed = len(vals) > 1
                value = "" if (mixed or not vals) else next(iter(vals))
                if key == "compilation":
                    w.set_state(None if (mixed or not tracks) else ("1" if value else ""), show_label=bool(tracks))
                    continue
                if key == "lyrics":
                    w.setPlainText(value)
                    w.setPlaceholderText(MIXED_HINT if mixed else "")
                else:
                    w.setText(value)
                    w.setPlaceholderText(("mixed" if w.maximumWidth() < 120 else MIXED_HINT) if mixed else "")
                self.mark(w, "mixed" if mixed else "")
            self.populate_art(tracks)
        finally:
            self._populating = False
        self.update_buttons()

    def populate_art(self, tracks: list[Track]):
        self.art_label.setPixmap(QPixmap())
        if not tracks:
            self.art_label.setText(""); self.art_info.setText(""); return
        if self.draft_art is not None:
            if self.draft_art[0] == "remove":
                self.art_label.setText("Will be\nremoved")
                self.art_info.setText("not applied yet")
                return
            self.show_pixmap(self.draft_art[2], "not applied yet")
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
            side = self.art_label.width() - 4
            self.art_label.setPixmap(pix.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
        self.update_status()

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

    def apply_draft(self):
        """Stage the drafted edits on the tracks shown in the panel (does not write files)."""
        tracks = self.panel_tracks
        if not tracks or not self.has_draft():
            return
        for t in tracks:
            for k, v in self.draft.items():
                t.tags[k] = v
            if self.draft_art is not None:
                if self.draft_art[0] == "set":
                    t.set_art(self.draft_art[1], self.draft_art[2])
                else:
                    t.remove_art()
        self.draft, self.draft_art = {}, None
        self.refresh_tracks(tracks)
        self.populate_panel(tracks)
        self.update_status()
        self.statusBar().showMessage(f"Applied to {len(tracks)} track(s). Click \"Save to files\" (⌘S) to write them.", 6000)

    def discard_draft(self):
        if self.has_draft():
            self.populate_panel(self.panel_tracks)
            self.update_status()

    def update_buttons(self):
        draft = self.has_draft()
        n = len(self.panel_tracks)
        self.apply_btn.setEnabled(draft)
        self.discard_btn.setEnabled(draft)
        self.apply_btn.setText(f"Apply to {n} track{'s' if n != 1 else ''}" if n else "Apply")
        self.save_btn.setEnabled(draft or bool(self.dirty_tracks()))
        self.pending_label.setText("● Unapplied edits - click Apply" if draft else "")

    def after_change(self, tracks):
        self.refresh_tracks(tracks)
        self.update_status()
        self.update_buttons()

    # ---- cover art (drafted like everything else)
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
        self.update_buttons(); self.update_status()

    def remove_cover(self):
        if not self.panel_tracks:
            return
        self.draft_art = ("remove",)
        self.populate_art(self.panel_tracks)
        self.update_buttons(); self.update_status()

    # ---- tools
    def need_selection(self) -> list[Track]:
        if self.has_draft():
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
        if self.has_draft():
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
        self.refresh_tracks(tracks)
        self.update_status()

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
        n, sel, dirty = len(self.tracks), len(self.selected_tracks()), len(self.dirty_tracks())
        parts = [f"{n} file{'s' if n != 1 else ''}"]
        if sel:
            parts.append(f"{sel} selected")
        if self.has_draft():
            parts.append("unapplied edits")
        if dirty:
            parts.append(f"{dirty} unsaved")
        self.setWindowTitle(f"{APP_NAME}{' — ' + str(dirty) + ' unsaved' if dirty else ''}")
        self.act_save.setEnabled(bool(dirty) or self.has_draft())
        self.statusBar().showMessage("  ·  ".join(parts))

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
