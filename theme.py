"""theme.py - TagBee's colour tokens and stylesheet, matching MacBee's design system.

Every colour the app uses lives here. Views ask for a token (background, surface, accent, ...)
instead of hard-coding colours. Values are copied from MacBee's Theme/Theme.swift.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette

# (key, menu title). "system" follows macOS: Dark in dark mode, Light in light mode.
THEME_CHOICES = [("dark", "Dark"), ("gray", "Medium Gray"), ("light", "Light"), ("system", "Match System")]
DEFAULT_THEME = "dark"

# MacBee's preset accent colours (key, menu title, hex).
ACCENT_CHOICES = [
    ("cyan", "Cyan", "#33D6E0"), ("violet", "Violet", "#9B7BFF"), ("orange", "Orange", "#FF8A3D"),
    ("green", "Green", "#3DDC84"), ("pink", "Pink", "#FF5C93"),
]
DEFAULT_ACCENT = "#33D6E0"

CORNER = 6          # MacBee Metrics.corner
HOVER_MS = 150      # MacBee hover animations: 150 ms ease-out


def _white(a: float) -> QColor:
    return QColor(255, 255, 255, round(a * 255))


def _black(a: float) -> QColor:
    return QColor(0, 0, 0, round(a * 255))


@dataclass
class Theme:
    kind: str
    accent: QColor
    on_accent: QColor        # text drawn on top of the accent colour
    background: QColor       # main content area (track list)
    sidebar: QColor          # left sidebar
    bar: QColor              # inspector panel and status bar
    surface: QColor          # fields, buttons, hovered rows
    elevated: QColor         # selected rows, hovered buttons
    separator: QColor
    text_primary: QColor
    text_secondary: QColor
    text_tertiary: QColor
    good: QColor
    warning: QColor          # "multiple values" and unsaved rows
    danger: QColor           # clearing a field

    @property
    def is_dark(self) -> bool:
        return self.kind != "light"

    @staticmethod
    def make(kind: str, accent: str = DEFAULT_ACCENT) -> "Theme":
        acc = QColor(accent)
        if not acc.isValid():
            acc = QColor(DEFAULT_ACCENT)
        light_accent = 0.299 * acc.redF() + 0.587 * acc.greenF() + 0.114 * acc.blueF() > 0.55
        on_accent = QColor("black") if light_accent else QColor("white")
        if kind == "gray":
            return Theme(kind, acc, on_accent,
                         background=QColor("#2B2B2F"), sidebar=QColor("#232327"), bar=QColor("#323237"),
                         surface=QColor("#38383E"), elevated=QColor("#44444B"), separator=_white(0.08),
                         text_primary=QColor("white"), text_secondary=_white(0.66), text_tertiary=_white(0.42),
                         good=QColor("#3DDC84"), warning=QColor("#FFB340"), danger=QColor("#FF6B6B"))
        if kind == "light":
            return Theme(kind, acc, on_accent,
                         background=QColor("#F7F7F8"), sidebar=QColor("#EDEDF0"), bar=QColor("white"),
                         surface=QColor("#E9E9EC"), elevated=QColor("#DEDEE3"), separator=_black(0.08),
                         text_primary=_black(0.88), text_secondary=_black(0.58), text_tertiary=_black(0.38),
                         good=QColor("#1E9E5A"), warning=QColor("#C77700"), danger=QColor("#D93636"))
        return Theme("dark", acc, on_accent,
                     background=QColor("#0E0E10"), sidebar=QColor("#09090B"), bar=QColor("#141417"),
                     surface=QColor("#1C1C20"), elevated=QColor("#26262B"), separator=_white(0.07),
                     text_primary=QColor("white"), text_secondary=_white(0.62), text_tertiary=_white(0.38),
                     good=QColor("#3DDC84"), warning=QColor("#FFB340"), danger=QColor("#FF6B6B"))

    # ---- helpers
    def tint(self, color: QColor, alpha: float) -> QColor:
        c = QColor(color); c.setAlphaF(alpha); return c

    @property
    def accent_text(self) -> QColor:
        """Accent used for text and icons, adjusted so it stays readable:
        lighter on dark themes (a dark custom accent), darker on Light."""
        c = QColor(self.accent)
        if self.is_dark:
            h, s, l, a = c.getHslF()
            return QColor.fromHslF(max(h, 0.0), s, l, a) if l >= 0.6 else QColor.fromHslF(max(h, 0.0), s, 0.6, a)
        while c.lightnessF() > 0.42:
            c = c.darker(110)
        return c

    def accent_hover(self) -> QColor:
        return self.accent.lighter(112) if self.is_dark else self.accent.darker(108)

    def pending_row(self) -> QColor:
        """Background of a track with unsaved changes."""
        return self.tint(self.warning, 0.16 if self.is_dark else 0.20)

    def palette(self) -> QPalette:
        p = QPalette()
        roles = {
            QPalette.Window: self.background, QPalette.WindowText: self.text_primary,
            QPalette.Base: self.background, QPalette.AlternateBase: self.surface,
            QPalette.Text: self.text_primary, QPalette.Button: self.surface,
            QPalette.ButtonText: self.text_primary, QPalette.BrightText: self.danger,
            QPalette.Highlight: self.elevated, QPalette.HighlightedText: self.text_primary,
            QPalette.ToolTipBase: self.elevated, QPalette.ToolTipText: self.text_primary,
            QPalette.PlaceholderText: self.text_tertiary, QPalette.Link: self.accent,
            QPalette.Mid: self.separator, QPalette.Dark: self.sidebar, QPalette.Light: self.elevated,
        }
        for role, color in roles.items():
            p.setColor(role, color)
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            p.setColor(QPalette.Disabled, role, self.text_tertiary)
        return p

    def stylesheet(self) -> str:
        c = {k: css(v) for k, v in vars(self).items() if isinstance(v, QColor)}
        c.update(accent_hover=css(self.accent_hover()), accent_text=css(self.accent_text), accent_soft=css(self.tint(self.accent, 0.22)),
                 hover_soft=css(self.tint(self.text_primary, 0.04)),
                 separator_strong=css(self.tint(self.text_primary, 0.16)), r=CORNER)
        return """
            QWidget {{ color: {text_primary}; }}
            QMainWindow, QDialog, QMessageBox {{ background: {background}; }}
            QToolTip {{ background: {elevated}; color: {text_primary}; border: 1px solid {separator};
                border-radius: {r}px; padding: 4px 8px; }}

            /* ---- side panels */
            QWidget#sidebar {{ background: {sidebar}; }}
            QWidget#inspector, QWidget#inspector QScrollArea, QWidget#inspectorPanel {{ background: {bar}; }}
            QFrame#divider {{ background: {separator}; border: none; max-height: 1px; min-height: 1px; }}
            QSplitter::handle {{ background: {separator}; }}
            QSplitter::handle:horizontal {{ width: 1px; }}
            QStatusBar {{ background: {sidebar}; color: {text_tertiary}; border-top: 1px solid {separator}; }}
            QStatusBar QLabel {{ color: {text_tertiary}; }}

            /* ---- text */
            QLabel {{ color: {text_primary}; background: transparent; }}
            QLabel#muted {{ color: {text_secondary}; }}
            QLabel#faint, QLabel#section, QLabel#fieldlabel {{ color: {text_tertiary}; }}
            QLabel:disabled {{ color: {text_tertiary}; }}
            QLabel#brand, QLabel#paneltitle, QLabel#emptytitle {{ color: {text_primary}; }}
            QLabel#pending, QLabel#mixedlabel {{ color: {warning}; }}
            QLabel#cover {{ background: {surface}; color: {text_tertiary}; border-radius: {r}px; }}
            QWidget#dropzone {{ border: 1px dashed {separator_strong}; border-radius: 10px; background: transparent; }}
            QWidget#dropzone:hover {{ border: 1px dashed {accent}; background: {hover_soft}; }}
            QLabel#droptitle {{ color: {text_secondary}; }}
            QWidget#dropzone[state="drag"] {{ border: 2px dashed {accent}; background: {hover_soft}; }}
            QStackedWidget#center[state="drag"] {{ border: 2px solid {accent}; }}
            QLabel#taglabel {{ color: {text_secondary}; }}
            QWidget#inspectorPanel QLineEdit, QWidget#inspectorPanel QPlainTextEdit {{ padding: 2px 6px; }}
            QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;
                border: 1px solid {separator_strong}; background: {surface}; }}
            QCheckBox::indicator:hover {{ border: 1px solid {accent}; }}
            QCheckBox::indicator:checked {{ background: {accent}; border: 1px solid {accent}; }}
            QCheckBox::indicator:indeterminate {{ background: {surface}; border: 1px dashed {warning}; }}
            QLabel#dropdetail {{ color: {text_tertiary}; }}

            /* ---- fields */
            QLineEdit, QPlainTextEdit, QSpinBox {{
                background: {surface}; color: {text_primary}; border: 1px solid transparent;
                border-radius: {r}px; padding: 5px 9px; placeholder-text-color: {text_tertiary};
                selection-background-color: {accent_soft}; selection-color: {text_primary}; }}
            QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover {{ background: {elevated}; }}
            QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border: 1px solid {accent}; background: {elevated}; }}
            QLineEdit:disabled, QPlainTextEdit:disabled {{ background: {surface}; color: {text_tertiary}; }}
            QLineEdit[state="mixed"], QPlainTextEdit[state="mixed"] {{
                border: 1px dashed {warning}; placeholder-text-color: {warning}; }}
            QLineEdit[state="edited"], QPlainTextEdit[state="edited"] {{ border: 1px solid {accent}; }}
            QLineEdit[state="cleared"], QPlainTextEdit[state="cleared"] {{
                border: 1px solid {danger}; placeholder-text-color: {danger}; }}

            /* ---- dialog buttons: MacBee capsules (the main window uses widgets.FlatButton) */
            QPushButton {{ background: {surface}; color: {accent_text}; border: none; font-weight: bold;
                border-radius: 15px; padding: 4px 18px; min-height: 22px; }}
            QPushButton:hover {{ background: {elevated}; }}
            QPushButton:pressed {{ background: {separator}; }}
            QPushButton:default {{ background: {accent}; color: {on_accent}; }}
            QPushButton:default:hover {{ background: {accent_hover}; }}
            QPushButton:disabled {{ background: {surface}; color: {text_tertiary}; }}
            QCheckBox, QGroupBox {{ color: {text_secondary}; }}
            QGroupBox {{ font-weight: bold; border: none; margin-top: 8px; }}
            QDialogButtonBox QPushButton {{ min-width: 72px; }}

            /* ---- track list */
            QTableView {{ background: {background}; border: none; outline: 0;
                selection-background-color: {elevated}; selection-color: {text_primary}; }}
            QTableView::item {{ padding: 0 6px; border: none; }}
            QTableView::item:selected {{ background: {elevated}; color: {text_primary}; }}
            QHeaderView {{ background: {background}; border: none; }}
            QHeaderView::section {{ background: {background}; color: {text_tertiary}; border: none;
                border-bottom: 1px solid {separator}; padding: 8px 6px 8px 7px; }}
            QHeaderView::section:hover {{ color: {text_primary}; }}
            QTableCornerButton::section {{ background: {background}; border: none; }}

            /* ---- scroll bars: thin, quiet */
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
            QScrollBar::handle {{ background: {separator}; border-radius: 3px; min-height: 24px; min-width: 24px; }}
            QScrollBar::handle:hover {{ background: {text_tertiary}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

            /* ---- pop-up menus (right-click), progress */
            QMenu {{ background: {elevated}; color: {text_primary}; border: 1px solid {separator};
                border-radius: {r}px; padding: 4px; }}
            QMenu::item {{ padding: 5px 22px 5px 22px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {accent}; color: {on_accent}; }}
            QMenu::separator {{ height: 1px; background: {separator}; margin: 4px 6px; }}
            QProgressBar {{ background: {surface}; border: none; border-radius: 3px; text-align: center; }}
            QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
        """.format(**c)


def css(color: QColor) -> str:
    """QColor -> stylesheet colour (keeps transparency)."""
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


# The active theme. MainWindow.apply_theme() replaces it; widgets.FlatButton paints from it.
current = Theme.make(DEFAULT_THEME)
