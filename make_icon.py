# Draws the TagBee app icon (icon.png, 1024 x 1024) to match MacBee's Vinyl Bee icon:
# dark rounded square, a big amber luggage tag on a string, and MacBee's striped bee on the tag.
# Usage: .venv.nosync/bin/python make_icon.py
import math
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QRadialGradient, QTransform)

app = QGuiApplication([])
S = 1024
img = QImage(S, S, QImage.Format_ARGB32); img.fill(Qt.transparent)
p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)


def rgba(hex_, a=1.0):
    c = QColor(hex_); c.setAlphaF(a); return c


# macOS icon body: 824 px rounded square with a soft shadow
body = QPainterPath(); body.addRoundedRect(QRectF(100, 100, 824, 824), 185, 185)
for i in range(14, 0, -1):                       # cheap blurred shadow
    sh = QPainterPath(); sh.addRoundedRect(QRectF(100 - i, 114 - i * 0.4, 824 + 2 * i, 824 + 2 * i), 185 + i, 185 + i)
    p.fillPath(sh, rgba("#000000", 0.035))
g = QLinearGradient(0, 100, 0, 924); g.setColorAt(0, QColor("#33363C")); g.setColorAt(1, QColor("#0A0B0D"))
p.fillPath(body, QBrush(g))
p.save(); p.setClipPath(body)

# warm amber glow behind the tag
glow = QRadialGradient(QPointF(512, 540), 430); glow.setColorAt(0, rgba("#FFB02E", 0.22)); glow.setColorAt(1, rgba("#FFB02E", 0))
p.fillRect(QRectF(0, 0, S, S), QBrush(glow))


def amber(y0, y1):
    ag = QLinearGradient(0, y0, 0, y1)
    ag.setColorAt(0, QColor("#FFD45A")); ag.setColorAt(0.55, QColor("#FFA82A")); ag.setColorAt(1, QColor("#F2851C"))
    return QBrush(ag)


# the tag, pointing up-right, with a punched hole near the tip
TW, TH, ANGLE, TCX, TCY = 600, 400, -20, 520, 540
tip = TW * 0.30
tag = QPainterPath()
tag.moveTo(-TW / 2, -TH / 2); tag.lineTo(TW / 2 - tip, -TH / 2); tag.lineTo(TW / 2, 0)
tag.lineTo(TW / 2 - tip, TH / 2); tag.lineTo(-TW / 2, TH / 2); tag.closeSubpath()
ts = QPainterPathStroker(); ts.setWidth(50); ts.setJoinStyle(Qt.RoundJoin)
tag = tag.united(ts.createStroke(tag)).simplified()
hole_x = TW / 2 - tip * 0.95
hole = QPainterPath(); hole.addEllipse(QPointF(hole_x, 0), 46, 46)
tag = tag.subtracted(hole)
t = QTransform(); t.translate(TCX, TCY); t.rotate(ANGLE); tag = t.map(tag)
for i in range(10, 0, -1):                       # soft shadow under the tag
    p.save(); p.translate(0, 12); p.setOpacity(0.05)
    p.setPen(QPen(QColor("black"), i * 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.drawPath(tag); p.restore()
p.fillPath(tag, amber(250, 860))

# string looped through the hole, running off to the top right
a = math.radians(ANGLE); hx = TCX + math.cos(a) * hole_x; hy = TCY + math.sin(a) * hole_x
string = QPainterPath(); string.moveTo(hx, hy); string.cubicTo(hx + 80, hy - 30, 760, 230, 850, 170)
p.setPen(QPen(rgba("#FFF4D6", 0.95), 16, Qt.SolidLine, Qt.RoundCap)); p.setBrush(Qt.NoBrush); p.drawPath(string)

# MacBee's bee: cream wings, striped amber/black body
p.save(); p.translate(TCX - 45, TCY + 28); p.rotate(ANGLE)
w = 275; h = w * 0.62
for side in (-1, 1):
    p.save(); p.translate(side * w * 0.16, -h * 0.55); p.rotate(side * 28)
    wg = QLinearGradient(0, -w * 0.3, 0, w * 0.3); wg.setColorAt(0, rgba("#FFF8E1", 0.95)); wg.setColorAt(1, rgba("#E8D9A8", 0.85))
    p.setBrush(QBrush(wg)); p.setPen(QPen(rgba("#FFFFFF", 0.9), w * 0.018)); p.drawEllipse(QRectF(-w * 0.17, -w * 0.30, w * 0.34, w * 0.60))
    p.restore()
oval = QPainterPath(); oval.addEllipse(QRectF(-w / 2, -h / 2, w, h))
p.fillPath(oval, QColor("#17130C"))
p.save(); p.setClipPath(oval)
for k in (1, 3, 5):
    p.fillRect(QRectF(-w / 2 + k * w / 7, -h / 2, w / 7, h), amber(-h / 2, h / 2))
p.restore(); p.restore()

p.restore(); p.end()
img.save("icon.png")
print("wrote icon.png")
