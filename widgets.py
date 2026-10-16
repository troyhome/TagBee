"""widgets.py - MacBee-style controls for TagBee: icon rows, flat icon buttons, capsules, segmented switch.

They paint themselves from theme.current (no button chrome), so they follow the theme and accent.
Icons are SF Symbols saved by make_symbols.swift into icons/.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import theme

_cache: dict = {}


def icon_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for cand in (base / "icons", base.parent / "Resources" / "icons"):
        if cand.is_dir():
            return cand
    return base / "icons"


def symbol(name: str, color: QColor, size: int, dpr: float = 2.0) -> QPixmap:
    """An SF Symbol tinted with `color`, `size` points square."""
    key = (name, color.rgba(), size, dpr)
    if key not in _cache:
        src = QPixmap(str(icon_dir() / f"{name}.png"))
        px = max(1, int(size * dpr))
        pix = QPixmap(px, px); pix.fill(Qt.transparent)
        if not src.isNull():
            p = QPainter(pix); p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(0, 0, src.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(pix.rect(), color); p.end()
        pix.setDevicePixelRatio(dpr)
        _cache[key] = pix
    return _cache[key]


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Blend colour a towards b (t = 0..1)."""
    return QColor.fromRgbF(*(x + (y - x) * t for x, y in zip(a.getRgbF(), b.getRgbF())))


def eyebrow_font(base: QFont) -> QFont:
    """MacBee's small section label: tiny, semibold, spaced out (used with UPPERCASE text)."""
    f = QFont(base); f.setPointSizeF(max(8.0, base.pointSizeF() * 0.66)); f.setWeight(QFont.DemiBold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
    return f


class FlatButton(QAbstractButton):
    """One button class, several MacBee looks:

    row      sidebar row: icon + text, highlights on hover; on click it lights up (accent icon) and fades out
    plain    icon (+ text) with no background; brightens on hover (MacBee BarIconButton)
    capsule  rounded pill, surface colour, accent text (MacBee Play button)
    accent   rounded pill filled with the accent colour (main action)
    segment  one half of a Yes/No switch; checked = raised + accent
    clear    small ✕ icon in a field; turns red on hover, hidden when disabled
    """

    def __init__(self, text: str = "", icon: str | None = None, kind: str = "row", tip: str | None = None):
        super().__init__()
        self.setText(text)
        self.icon_name, self.kind = icon, kind
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        if tip:
            self.setToolTip(tip)
        self._flash = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(450); self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_flash)
        if kind == "row":
            self.clicked.connect(self.flash)

    # ---- click highlight (fades over ~0.45 s, like a selection that lets go)
    def flash(self):
        self._anim.stop(); self._anim.setStartValue(1.0); self._anim.setEndValue(0.0); self._anim.start()

    def _on_flash(self, v):
        self._flash = float(v); self.update()

    # ---- size
    def _icon_pt(self) -> int:
        """Icon box size. Symbols fill about half their box, so the glyph matches the text size (MacBee: 14 pt icon, 13 pt text)."""
        fm = self.fontMetrics()
        return int(fm.height() * (1.45 if self.kind == "clear" else 1.75))

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        icon_w = self._icon_pt() if self.icon_name else 0
        gap = 3 if (text_w and icon_w) else 0
        if self.kind == "row":
            return QSize(20 + icon_w + gap + text_w, max(30, int(fm.height() * 1.85)))
        if self.kind in ("plain", "clear"):
            return QSize(icon_w + gap + text_w + 8, int(fm.height() * 1.6))
        h = int(fm.height() * 2.0)
        return QSize(icon_w + gap + text_w + int(h * 0.9), h)

    def minimumSizeHint(self) -> QSize:
        s = self.sizeHint()
        return QSize(min(s.width(), 40), s.height()) if self.kind == "row" else s

    # ---- painting
    def paintEvent(self, e):
        t = theme.current
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        on, hover, down = self.isEnabled(), self.underMouse() and self.isEnabled(), self.isDown()
        checked = self.isChecked()
        bold = False
        bg = None

        if self.kind == "row":
            active = down or self._flash > 0
            if active:
                bg = mix(t.surface, t.elevated, max(self._flash, 1.0 if down else 0.0))
            elif hover:
                bg = t.surface
            icon_c = mix(t.text_secondary, t.accent_text, 1.0 if down else self._flash) if on else t.text_tertiary
            text_c = (t.text_primary if (hover or active) else t.text_secondary) if on else t.text_tertiary
            bold = down or self._flash > 0.5
            radius, align = theme.CORNER, Qt.AlignLeft
        elif self.kind == "plain":
            icon_c = text_c = (t.text_primary if hover else t.text_secondary) if on else t.text_tertiary
            radius, align = theme.CORNER, Qt.AlignCenter
        elif self.kind == "clear":
            box = self.parentWidget()
            if not on or not (hover or (box is not None and box.underMouse())):
                return                     # only shown while the mouse is over its field, like MacBee's search field
            icon_c = text_c = t.danger if hover else t.text_tertiary
            radius, align = theme.CORNER, Qt.AlignCenter
        elif self.kind == "segment":
            if checked:
                bg, icon_c, text_c, bold = t.elevated, t.accent_text, t.accent_text, True
            else:
                bg = t.tint(t.text_primary, 0.05) if hover else None
                icon_c = text_c = t.text_primary if hover else t.text_secondary
            radius, align = r.height() / 2, Qt.AlignCenter
        elif self.kind == "accent":
            bg = (t.accent_hover() if hover else t.accent) if on else t.surface
            icon_c = text_c = t.on_accent if on else t.text_tertiary
            bold, radius, align = True, r.height() / 2, Qt.AlignCenter
        else:  # capsule
            bg = (t.elevated if hover else t.surface)
            icon_c = text_c = t.accent_text if on else t.text_tertiary
            bold, radius, align = True, r.height() / 2, Qt.AlignCenter
        if down and self.kind in ("capsule", "accent", "plain"):
            p.setOpacity(0.75)

        if bg is not None:
            path = QPainterPath(); path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
            p.fillPath(path, bg)

        f = QFont(self.font()); f.setWeight(QFont.DemiBold if bold else QFont.Normal); p.setFont(f)
        fm = p.fontMetrics()
        icon_pt = self._icon_pt() if self.icon_name else 0
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        gap = 3 if (icon_pt and text_w) else 0
        x = 4.0 if align == Qt.AlignLeft else (r.width() - icon_pt - gap - text_w) / 2
        if icon_pt:
            p.drawPixmap(int(x), int((r.height() - icon_pt) / 2), symbol(self.icon_name, icon_c, icon_pt, self.devicePixelRatioF()))
            x += icon_pt + gap
        if text_w:
            p.setPen(text_c)
            avail = int(r.width() - x - (10 if align == Qt.AlignLeft else 0))
            p.drawText(QRectF(x, 0, max(0, avail), r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(self.text(), Qt.ElideRight, max(0, avail)))
        p.end()


class Segmented(QWidget):
    """Pill-shaped container for segment buttons (Yes / No)."""

    def __init__(self, *buttons: FlatButton):
        super().__init__()
        row = QHBoxLayout(self); row.setContentsMargins(3, 3, 3, 3); row.setSpacing(2)
        for b in buttons:
            row.addWidget(b)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()); path = QPainterPath(); path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, theme.current.surface); p.end()


class FieldBox(QWidget):
    """Holds a field and its clear button; shows the button while the mouse is over the field."""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_Hover)

    def event(self, e):
        if e.type() in (e.Type.HoverEnter, e.Type.HoverLeave):
            for b in self.findChildren(FlatButton):
                b.update()
        return super().event(e)


class DropZone(QWidget):
    """Quiet dashed drop target with an icon; click to choose files."""
    clicked = Signal()

    def __init__(self, title: str, detail: str):
        super().__init__()
        self.setObjectName("dropzone")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 14, 14, 14); lay.setSpacing(6)
        self.icon = QLabel(); self.icon.setAlignment(Qt.AlignCenter)
        self.title = QLabel(title); self.title.setAlignment(Qt.AlignCenter); self.title.setObjectName("droptitle")
        self.detail = QLabel(detail); self.detail.setAlignment(Qt.AlignCenter); self.detail.setObjectName("dropdetail")
        self.title.setWordWrap(True); self.detail.setWordWrap(True)
        lay.addStretch(1); lay.addWidget(self.icon); lay.addWidget(self.title); lay.addWidget(self.detail); lay.addStretch(1)
        self.refresh()

    def refresh(self):
        t = theme.current
        size = int(self.title.fontMetrics().height() * 3.2)
        self.icon.setPixmap(symbol("arrow.down.to.line", t.accent if self.underMouse() else t.text_tertiary, size,
                                   self.devicePixelRatioF()))

    def event(self, e):
        if e.type() in (e.Type.HoverEnter, e.Type.HoverLeave):
            self.refresh()
        return super().event(e)

    def mousePressEvent(self, e):
        self.clicked.emit()
