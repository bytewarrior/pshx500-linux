"""Stereo level meter widget (vertical bars, peak hold, OVER)."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

FLOOR = -60.0
TOP = 6.0
# (lower dB limit, upper dB limit, colour)
ZONES = [(-60.0, -12.0, (60, 200, 70)),
         (-12.0, -3.0, (225, 205, 45)),
         (-3.0, 6.0, (220, 60, 60))]


class MeterWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(140, 260)
        self._ch = [{"peak_db": FLOOR, "hold_db": FLOOR, "over": False} for _ in range(2)]

    def set_levels(self, channels) -> None:
        self._ch = channels
        self.update()

    @staticmethod
    def _y(db: float, top: int, bot: int) -> int:
        db = max(FLOOR, min(TOP, db))
        frac = (db - FLOOR) / (TOP - FLOOR)
        return int(bot - frac * (bot - top))

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(28, 28, 30))
        w, h = self.width(), self.height()
        font = p.font(); font.setPointSize(8); p.setFont(font)

        # Geometry: [margin][scale][bar L][gap][bar R][margin]
        margin = 6
        scale_w = 26
        gap = 8
        top = 16               # room for the OVER lamp
        bot = h - 18           # room for the L/R label
        x_bars = margin + scale_w
        barw = max(6, (w - x_bars - margin - gap) // 2)
        xs = [x_bars, x_bars + barw + gap]

        # dB scale on the left
        p.setPen(QtGui.QColor(130, 130, 130))
        for db in (0, -6, -12, -24, -36, -48, -60):
            y = self._y(db, top, bot)
            p.drawText(margin, y - 6, scale_w - 3, 12,
                       QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, f"{db}")

        for i in range(2):
            x = xs[i]
            p.fillRect(x, top, barw, bot - top, QtGui.QColor(12, 12, 12))
            ch = self._ch[i]
            ylevel = self._y(ch["peak_db"], top, bot)
            for lo, hi, color in ZONES:
                seg_bot = self._y(lo, top, bot)
                seg_top = self._y(hi, top, bot)
                fill_top = max(seg_top, ylevel)
                if fill_top < seg_bot:
                    p.fillRect(x, fill_top, barw, seg_bot - fill_top, QtGui.QColor(*color))
            # Peak hold
            yh = self._y(ch["hold_db"], top, bot)
            p.fillRect(x, yh - 1, barw, 2, QtGui.QColor(240, 240, 240))
            # OVER lamp
            over_col = QtGui.QColor(230, 40, 40) if ch["over"] else QtGui.QColor(60, 30, 30)
            p.fillRect(x, top - 8, barw, 5, over_col)
            # Channel label (L/R); no numeric level display (the bars are enough)
            p.setPen(QtGui.QColor(220, 220, 220))
            p.drawText(x, bot + 2, barw, 14, QtCore.Qt.AlignCenter, "L" if i == 0 else "R")
