# Draws the TagBee app icon (icon.png, 1024 x 1024) in MacBee's style:
# dark rounded square, cyan glow, glassy wings, amber honeycomb - with a tag instead of MacBee's bars.
# Usage: .venv.nosync/bin/python make_icon.py
import math
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QRadialGradient)

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
g = QLinearGradient(0, 100, 0, 924); g.setColorAt(0, QColor("#1E252C")); g.setColorAt(1, QColor("#07090B"))
p.fillPath(body, QBrush(g))
p.save(); p.setClipPath(body)

# cyan glow behind the hexagon (MacBee's accent colour)
glow = QRadialGradient(QPointF(512, 554), 420); glow.setColorAt(0, rgba("#33D6E0", 0.42)); glow.setColorAt(1, rgba("#33D6E0", 0))
p.fillRect(QRectF(0, 0, S, S), QBrush(glow))


def wing(cx, cy, angle_deg):
    p.save(); p.translate(cx, cy); p.rotate(angle_deg)
    rect = QRectF(-160, -70, 320, 140)
    wg = QLinearGradient(160, 0, -160, 0); wg.setColorAt(0, rgba("#FFFFFF", 0.80)); wg.setColorAt(1, rgba("#9FEFF5", 0.30))
    p.setBrush(QBrush(wg)); p.setPen(QPen(rgba("#FFFFFF", 0.85), 5)); p.drawEllipse(rect)
    p.restore()


# same wing positions as MacBee (converted to top-down coordinates)
wing(380, 279, math.degrees(2.45))
wing(644, 279, math.degrees(0.69))

# honeycomb hexagon (flat top), amber, rounded corners
cx, cy, r = 512, 569, 255
hexp = QPainterPath()
for i in range(6):
    a = i * math.pi / 3
    pt = QPointF(cx + r * math.cos(a), cy + r * math.sin(a))
    hexp.moveTo(pt) if i == 0 else hexp.lineTo(pt)
hexp.closeSubpath()
st = QPainterPathStroker(); st.setWidth(40); st.setJoinStyle(Qt.RoundJoin); st.setCapStyle(Qt.RoundCap)
hexshape = hexp.united(st.createStroke(hexp)).simplified()
for i in range(10, 0, -1):
    p.save(); p.translate(0, 10); p.setOpacity(0.05); p.setPen(QPen(QColor("black"), i * 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(hexshape); p.restore()
hg = QLinearGradient(0, cy - r, 0, cy + r)
hg.setColorAt(0, QColor("#FFDA5C")); hg.setColorAt(0.6, QColor("#FFA51F")); hg.setColorAt(1, QColor("#F2851A"))
p.fillPath(hexshape, QBrush(hg))

# the tag (TagBee's mark), dark like MacBee's bars, with a punched hole
p.save(); p.translate(cx, cy); p.rotate(-12)
tag = QPainterPath()
tag.moveTo(-150, -100); tag.lineTo(60, -100); tag.lineTo(165, 0); tag.lineTo(60, 100); tag.lineTo(-150, 100); tag.closeSubpath()
ts = QPainterPathStroker(); ts.setWidth(36); ts.setJoinStyle(Qt.RoundJoin)
tag = tag.united(ts.createStroke(tag)).simplified()
hole = QPainterPath(); hole.addEllipse(QPointF(-95, 0), 30, 30)
p.fillPath(tag.subtracted(hole), QColor("#15110C"))
p.restore()

# light sheen across the top
sheen = QLinearGradient(0, 100, 0, 384); sheen.setColorAt(0, rgba("#FFFFFF", 0.10)); sheen.setColorAt(1, rgba("#FFFFFF", 0))
p.fillRect(QRectF(0, 0, S, S), QBrush(sheen))
p.restore(); p.end()
img.save("icon.png")
print("wrote icon.png")
