import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QBrush, QPolygonF
app = QGuiApplication([])
S = 1024
img = QImage(S, S, QImage.Format_ARGB32); img.fill(Qt.transparent)
p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
bg = QPainterPath(); bg.addRoundedRect(QRectF(60, 60, S - 120, S - 120), 210, 210)
g = QLinearGradient(0, 60, 0, S - 60); g.setColorAt(0, QColor("#4f9cf5")); g.setColorAt(1, QColor("#2a55c9"))
p.fillPath(bg, QBrush(g))
# tag shape (white), tilted
p.save(); p.translate(S / 2, S / 2); p.rotate(-12)
tag = QPainterPath()
tag.moveTo(-270, -190); tag.lineTo(90, -190); tag.lineTo(300, 0); tag.lineTo(90, 190); tag.lineTo(-270, 190); tag.closeSubpath()
tag.addEllipse(QPointF(-190, 0), 42, 42)       # punch hole
p.fillPath(tag, QColor(255, 255, 255, 245))
p.restore()
# music note on the tag
p.setPen(Qt.NoPen); p.setBrush(QColor("#2a55c9"))
p.save(); p.translate(S / 2 - 5, S / 2 + 2)
p.drawEllipse(QRectF(-85, 45, 100, 76))
p.drawRect(QRectF(-3, -120, 24, 190))
flag = QPainterPath(); flag.moveTo(21, -120); flag.cubicTo(110, -95, 125, -40, 105, 15); flag.lineTo(82, 5); flag.cubicTo(98, -35, 85, -65, 21, -85); flag.closeSubpath()
p.drawPath(flag)
p.restore(); p.end()
img.save("icon.png")
