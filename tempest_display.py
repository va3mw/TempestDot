"""
Tempest Weather Station Display
Listens for UDP broadcasts on port 50222 and renders a LightMap-style GUI.
Press M or tap the unit toggle to switch Metric / Imperial.
Requires: python3-pyqt5
"""

import sys
import os
import json
import socket
import threading
import math
import time
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QRectF, QPointF
from PyQt5.QtGui import (QPainter, QColor, QFont, QPen, QBrush,
                          QPainterPath)

UDP_PORT = 50222

# ── Colour palette ────────────────────────────────────────────────────────────
BG     = QColor(0x1a, 0x0a, 0x2e)
PINK   = QColor(0xff, 0x40, 0xa0)
YELLOW = QColor(0xff, 0xd0, 0x00)
CYAN   = QColor(0x00, 0xe0, 0xff)
ORANGE = QColor(0xff, 0x88, 0x00)
WHITE  = QColor(0xff, 0xff, 0xff)
GREY   = QColor(0x88, 0x88, 0x99)
DIM    = QColor(0x33, 0x22, 0x55)
GREEN  = QColor(0x00, 0xcc, 0x44)


# ══════════════════════════════════════════════════════════════════════════════
# UDP listener
# ══════════════════════════════════════════════════════════════════════════════
class TempestListener(QObject):
    data_received = pyqtSignal(dict)

    def start(self):
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", UDP_PORT))
        sock.settimeout(1.0)
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                self.data_received.emit(json.loads(data.decode()))
            except socket.timeout:
                pass
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Weather state — all values stored in SI; conversion happens at draw time
# ══════════════════════════════════════════════════════════════════════════════
class WeatherState:
    def __init__(self):
        self.wind_ms          = 0.0
        self.gust_ms          = 0.0
        self.wind_dir         = 0
        self.temp_c           = 20.0
        self.humidity         = 55.0
        self.pressure_mb      = 1013.0
        self.precip_rate_mmhr = 0.0
        self.precip_mm        = 0.0
        self.uv_index         = 0.0
        self.solar_rad        = 0.0
        self.conditions       = "clear"
        self.forecast_hour_dots = [0.5] * 12
        self.serial           = ""
        self.last_update      = None
        self.metric           = True

    @property
    def wind_display(self):
        return round(self.wind_ms * 3.6, 1) if self.metric else round(self.wind_ms * 2.237, 1)

    @property
    def gust_display(self):
        return round(self.gust_ms * 3.6, 1) if self.metric else round(self.gust_ms * 2.237, 1)

    @property
    def wind_unit(self):
        return "km/h" if self.metric else "mph"

    @property
    def temp_display(self):
        return round(self.temp_c, 1) if self.metric else round(self.temp_c * 9/5 + 32, 1)

    @property
    def temp_unit(self):
        return "°C" if self.metric else "°F"

    @property
    def pressure_display(self):
        return round(self.pressure_mb * 0.75006, 1) if self.metric else round(self.pressure_mb * 0.02953, 2)

    @property
    def pressure_unit(self):
        return "mmHg" if self.metric else "inHg"

    @property
    def precip_rate_display(self):
        return round(self.precip_rate_mmhr, 1) if self.metric else round(self.precip_rate_mmhr / 25.4, 3)

    @property
    def precip_accum_display(self):
        return round(self.precip_mm, 1) if self.metric else round(self.precip_mm / 25.4, 2)

    @property
    def precip_unit(self):
        return "mm" if self.metric else "in"

    def ingest(self, msg):
        t  = msg.get("type", "")
        sn = msg.get("serial_number", "")
        if sn and not self.serial:
            self.serial = sn

        if t == "obs_st":
            obs = msg.get("obs", [[]])[0]
            if len(obs) >= 18:
                if obs[2]  is not None: self.wind_ms     = float(obs[2])
                if obs[3]  is not None: self.gust_ms     = float(obs[3])
                if obs[4]  is not None: self.wind_dir    = int(obs[4])
                if obs[6]  is not None: self.pressure_mb = float(obs[6])
                if obs[7]  is not None: self.temp_c      = float(obs[7])
                if obs[8]  is not None: self.humidity    = float(obs[8])
                if obs[10] is not None: self.uv_index    = float(obs[10])
                if obs[11] is not None: self.solar_rad   = float(obs[11])
                if obs[12] is not None: self.precip_mm   = float(obs[12])
                pt = obs[13]
                if pt == 1:
                    self.conditions = "rain"
                elif pt == 2:
                    self.conditions = "hail"
                else:
                    if self.uv_index > 5:
                        self.conditions = "clear"
                    elif self.solar_rad > 100:
                        self.conditions = "partly"
                    else:
                        self.conditions = "cloudy"
                self.last_update = datetime.now()

        elif t == "rapid_wind":
            ob = msg.get("ob", [])
            if len(ob) >= 3:
                if ob[1] is not None: self.wind_ms  = float(ob[1])
                if ob[2] is not None: self.wind_dir = int(ob[2])

        elif t == "evt_precip":
            self.conditions = "rain"


# ══════════════════════════════════════════════════════════════════════════════
# Helper: linear tick scale with pointer triangle
# ══════════════════════════════════════════════════════════════════════════════
def draw_tick_scale(p, rect, min_val, max_val, value, ticks, color):
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    mid = y + h / 2
    p.setPen(QPen(GREY, 1))
    p.drawLine(int(x), int(mid), int(x + w), int(mid))

    for tv, lbl in ticks:
        frac = (tv - min_val) / (max_val - min_val)
        tx = x + frac * w
        p.drawLine(int(tx), int(mid - 5), int(tx), int(mid + 5))
        p.setPen(QPen(GREY))
        p.setFont(QFont("Arial", 7))
        p.drawText(int(tx - 12), int(mid + 6), 24, 12, Qt.AlignHCenter, lbl)
        p.setPen(QPen(GREY, 1))

    frac = max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))
    px = x + frac * w
    ptr = QPainterPath()
    ptr.moveTo(px, mid - 8)
    ptr.lineTo(px - 5, mid - 16)
    ptr.lineTo(px + 5, mid - 16)
    ptr.closeSubpath()
    p.fillPath(ptr, color)


# ══════════════════════════════════════════════════════════════════════════════
# Main widget  —  draws in a fixed 380x760 logical canvas that is then
# scaled and centred to fill whatever the actual window size is.
# ══════════════════════════════════════════════════════════════════════════════
CANVAS_W = 380
CANVAS_H = 760

class TempestWidget(QWidget):
    def __init__(self, state: WeatherState):
        super().__init__()
        self.state = state
        self.setWindowTitle("Tempest Weather Station")
        bg = f"#{BG.red():02x}{BG.green():02x}{BG.blue():02x}"
        self.setStyleSheet(f"background-color: {bg};")
        self.setFocusPolicy(Qt.StrongFocus)

        self._toggle_rect = QRectF(8, 30, 80, 18)  # logical canvas coords
        self._scale = 1.0
        self._x_off = 0.0
        self._y_off = 0.0

    def _to_logical(self, pos):
        lx = (pos.x() - self._x_off) / self._scale
        ly = (pos.y() - self._y_off) / self._scale
        return QPointF(lx, ly)

    # ── Input ─────────────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_M:
            self.state.metric = not self.state.metric
            self.update()
        elif event.key() in (Qt.Key_Q, Qt.Key_Escape):
            QApplication.quit()

    def mousePressEvent(self, event):
        lpos = self._to_logical(event.pos())
        if self._toggle_rect.contains(lpos):
            self.state.metric = not self.state.metric
            self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        p.fillRect(self.rect(), BG)

        scale_x = self.width()  / CANVAS_W
        scale_y = self.height() / CANVAS_H
        self._scale = min(scale_x, scale_y)
        self._x_off = (self.width()  - CANVAS_W * self._scale) / 2
        self._y_off = (self.height() - CANVAS_H * self._scale) / 2

        p.translate(self._x_off, self._y_off)
        p.scale(self._scale, self._scale)

        y = 8
        y = self._draw_header(p, y)
        y = self._draw_forecast_clock(p, y)
        y = self._draw_precip_intensity(p, y)
        y = self._draw_uv_index(p, y)
        y = self._draw_precip_accum(p, y)
        y = self._draw_conditions(p, y)
        y = self._draw_humidity_wind(p, y)
        y = self._draw_wind_gust_scale(p, y)
        y = self._draw_pressure_moon(p, y)
        self._draw_temp_bar(p, y)

    # ── Header ────────────────────────────────────────────────────────────────
    def _draw_header(self, p, y):
        W = CANVAS_W

        serial = self.state.serial or "Tempest Station"
        p.setFont(QFont("Arial", 9))
        p.setPen(QPen(GREY))
        p.drawText(8, y, W - 100, 18, Qt.AlignLeft | Qt.AlignVCenter, serial)

        p.setFont(QFont("Arial", 22, QFont.Bold))
        p.setPen(QPen(WHITE))
        p.drawText(0, y, W - 8, 26, Qt.AlignRight | Qt.AlignVCenter, "Tempest°")

        ty = y + 28
        btn_w = 84
        r = QRectF(8, ty, btn_w, 17)
        self._toggle_rect = r
        p.setBrush(QBrush(DIM))
        p.setPen(QPen(GREY, 1))
        p.drawRoundedRect(r, 4, 4)
        p.setFont(QFont("Arial", 7, QFont.Bold))
        p.setPen(QPen(CYAN))
        label = "● METRIC" if self.state.metric else "● IMPERIAL"
        p.drawText(r.toRect(), Qt.AlignHCenter | Qt.AlignVCenter, label)

        if self.state.last_update:
            ts = self.state.last_update.strftime("%H:%M:%S")
            p.setFont(QFont("Arial", 7))
            p.setPen(QPen(GREY))
            p.drawText(100, ty, W - 108, 17, Qt.AlignRight | Qt.AlignVCenter,
                       f"updated {ts}")

        return ty + 20

    # ── Forecast clock ────────────────────────────────────────────────────────
    def _draw_forecast_clock(self, p, y):
        p.setFont(QFont("Arial", 7))
        p.setPen(QPen(GREY))
        p.drawText(10, y, 200, 14, Qt.AlignLeft, "forecast")

        cx, cy, r = 78, y + 62, 44

        p.setPen(QPen(GREY, 1))
        for h in range(12):
            angle = math.radians(h * 30 - 90)
            x1 = cx + math.cos(angle) * (r - 5)
            y1 = cy + math.sin(angle) * (r - 5)
            x2 = cx + math.cos(angle) * r
            y2 = cy + math.sin(angle) * r
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
            nx = cx + math.cos(angle) * (r - 14)
            ny = cy + math.sin(angle) * (r - 14)
            p.drawText(int(nx - 7), int(ny - 6), 14, 12, Qt.AlignHCenter,
                       str(h if h > 0 else 12))

        for h, prob in enumerate(self.state.forecast_hour_dots):
            angle = math.radians(h * 30 - 90)
            dr = r + 8
            dx = cx + math.cos(angle) * dr
            dy = cy + math.sin(angle) * dr
            color = PINK if prob > 0.6 else (YELLOW if prob > 0.3 else DIM)
            p.setBrush(QBrush(color))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(dx, dy), 4, 4)

        now = datetime.now()
        ha = math.radians((now.hour % 12 + now.minute / 60) * 30 - 90)
        ma = math.radians(now.minute * 6 - 90)
        p.setPen(QPen(WHITE, 2))
        p.drawLine(cx, cy, int(cx + math.cos(ha) * (r - 22)), int(cy + math.sin(ha) * (r - 22)))
        p.setPen(QPen(YELLOW, 1))
        p.drawLine(cx, cy, int(cx + math.cos(ma) * (r - 12)), int(cy + math.sin(ma) * (r - 12)))
        p.setBrush(QBrush(WHITE))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 3, 3)

        self._draw_weather_icon(p, CANVAS_W - 120, y + 18, 110, 84)
        return y + 128

    def _draw_weather_icon(self, p, x, y, w, h):
        cond = self.state.conditions
        cx, cy = x + w // 2, y + h // 2
        if cond == "clear":
            p.setBrush(QBrush(YELLOW)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), 20, 20)
            p.setPen(QPen(YELLOW, 2))
            for a in range(0, 360, 45):
                ang = math.radians(a)
                p.drawLine(int(cx + math.cos(ang)*24), int(cy + math.sin(ang)*24),
                           int(cx + math.cos(ang)*31), int(cy + math.sin(ang)*31))
        elif cond in ("rain", "hail"):
            self._cloud(p, cx - 8, cy - 10, GREY, 30)
            p.setPen(QPen(CYAN, 2))
            for i in range(3):
                rx = cx - 14 + i * 12
                p.drawLine(rx, cy + 6, rx - 5, cy + 20)
        elif cond == "partly":
            p.setBrush(QBrush(YELLOW)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx - 10, cy - 10), 15, 15)
            self._cloud(p, cx, cy, QColor(0xaa, 0xaa, 0xbb), 22)
        else:
            self._cloud(p, cx, cy, QColor(0xaa, 0xaa, 0xbb), 30)

    def _cloud(self, p, cx, cy, color, sz):
        p.setBrush(QBrush(color)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), sz*0.5, sz*0.4)
        p.drawEllipse(QPointF(cx - sz*0.3, cy + sz*0.1), sz*0.35, sz*0.3)
        p.drawEllipse(QPointF(cx + sz*0.3, cy + sz*0.1), sz*0.35, sz*0.3)
        p.drawRect(int(cx - sz*0.65), int(cy + sz*0.05), int(sz*1.3), int(sz*0.35))

    # ── Precipitation intensity ───────────────────────────────────────────────
    def _draw_precip_intensity(self, p, y):
        W = CANVAS_W
        unit = self.state.precip_unit
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y, W - 20, 14, Qt.AlignLeft,
                   f"precipitation intensity  ({unit}/hr)")

        labels = ["light", "moderate", "heavy"]
        dots_per_seg, dot_r, gap = 8, 4, 3
        all_dots = dots_per_seg * 3
        total_w = all_dots * (dot_r * 2 + gap)
        ox = (W - total_w) // 2
        oy = y + 28

        max_rate = 20.0 if self.state.metric else 0.8
        rate = self.state.precip_rate_display
        rate_frac = min(1.0, rate / max_rate)
        active_dots = int(rate_frac * all_dots)

        for i in range(all_dots):
            seg = i // dots_per_seg
            color = [CYAN, YELLOW, PINK][seg] if i < active_dots else DIM
            cx = ox + i * (dot_r * 2 + gap) + dot_r
            p.setBrush(QBrush(color)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, oy), dot_r, dot_r)

        p.setPen(QPen(GREY)); p.setFont(QFont("Arial", 7))
        lx = [ox + k * dots_per_seg * (dot_r*2+gap) for k in range(3)]
        for lbl, x in zip(labels, lx):
            p.drawText(int(x), int(oy + 10), 55, 12, Qt.AlignLeft, lbl)

        return y + 55

    # ── UV index ──────────────────────────────────────────────────────────────
    def _draw_uv_index(self, p, y):
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y, 100, 14, Qt.AlignLeft, "uv index")
        p.drawText(160, y, 150, 14, Qt.AlignRight, "low ────── high ── extreme")

        W = CANVAS_W
        uv = self.state.uv_index
        n_dots, dot_r, gap = 20, 4, 3
        total_w = n_dots * (dot_r * 2 + gap)
        ox = (W - total_w) // 2
        oy = y + 30

        for i in range(n_dots):
            frac = i / n_dots
            c = GREEN if frac < 0.3 else (YELLOW if frac < 0.6 else (ORANGE if frac < 0.8 else PINK))
            active = (uv / 11.0) >= ((i + 1) / n_dots)
            p.setBrush(QBrush(c if active else DIM)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(ox + i * (dot_r*2+gap) + dot_r, oy), dot_r, dot_r)

        return y + 50

    # ── Precipitation accumulation ────────────────────────────────────────────
    def _draw_precip_accum(self, p, y):
        W = CANVAS_W
        unit = self.state.precip_unit
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y, W - 20, 14, Qt.AlignLeft,
                   f"precipitation accumulation, {unit}")

        if self.state.metric:
            vals = [1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 75]
        else:
            vals = [0.04, 0.08, 0.2, 0.4, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0]

        dot_r, gap = 5, 4
        total_w = len(vals) * (dot_r * 2 + gap)
        ox = (W - total_w) // 2
        oy = y + 30
        acc = self.state.precip_accum_display

        for i, v in enumerate(vals):
            cx = ox + i * (dot_r*2+gap) + dot_r
            p.setBrush(QBrush(CYAN if acc >= v else DIM)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, oy), dot_r, dot_r)
            p.setPen(QPen(GREY)); p.setFont(QFont("Arial", 6))
            lbl = str(int(v)) if self.state.metric else str(v)
            p.drawText(int(cx - 10), int(oy + 12), 20, 12, Qt.AlignHCenter, lbl)

        return y + 55

    # ── Conditions icons ──────────────────────────────────────────────────────
    def _draw_conditions(self, p, y):
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y, 100, 14, Qt.AlignLeft, "conditions")

        icons = [
            ("💧", "rain",    CYAN),
            ("⚡", "thunder", YELLOW),
            ("❄",  "snow",   WHITE),
            ("☁",  "cloudy", GREY),
            ("⛅", "partly", YELLOW),
            ("☀",  "clear",  YELLOW),
        ]
        for i, (sym, cond, color) in enumerate(icons):
            active = self.state.conditions == cond
            p.setFont(QFont("Arial", 14))
            p.setPen(QPen(color if active else DIM))
            p.drawText(28 + i * 38, y + 10, 28, 28, Qt.AlignHCenter, sym)

        return y + 45

    # ── Humidity dial + Wind compass ──────────────────────────────────────────
    def _draw_humidity_wind(self, p, y):
        W = CANVAS_W
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y, 100, 14, Qt.AlignLeft, "humidity")
        p.drawText(10, y, W - 14, 14, Qt.AlignRight, "wind\ndirection")

        cx, cy, r = 80, y + 68, 52
        p.setPen(QPen(DIM, 2)); p.setBrush(Qt.NoBrush)
        p.drawArc(int(cx-r), int(cy-r), int(r*2), int(r*2), 0, 360*16)

        hum = self.state.humidity
        p.setPen(QPen(PINK, 6))
        p.drawArc(int(cx-r), int(cy-r), int(r*2), int(r*2),
                  90*16, -int((hum/100)*360*16))

        p.setPen(QPen(GREY, 1))
        for pct in [0, 20, 40, 60, 80, 100]:
            ang = math.radians(90 - (pct/100)*360)
            x1 = cx + math.cos(ang)*(r-6);  y1 = cy - math.sin(ang)*(r-6)
            x2 = cx + math.cos(ang)*r;       y2 = cy - math.sin(ang)*r
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
            lx = cx + math.cos(ang)*(r-16)
            ly = cy - math.sin(ang)*(r-16)
            p.setFont(QFont("Arial", 6))
            p.drawText(int(lx-8), int(ly-6), 16, 12, Qt.AlignHCenter, str(pct))

        p.setFont(QFont("Arial", 14, QFont.Bold)); p.setPen(QPen(WHITE))
        p.drawText(int(cx-20), int(cy-10), 40, 20, Qt.AlignHCenter, f"{hum:.0f}")
        p.setFont(QFont("Arial", 8)); p.setPen(QPen(GREY))
        p.drawText(int(cx-10), int(cy+8), 20, 12, Qt.AlignHCenter, "%")

        cx2, cy2, r2 = W - 90, y + 68, 48
        p.setPen(QPen(GREY, 1)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx2, cy2), r2, r2)

        for lbl, ang in [("N", 0), ("E", 90), ("S", 180), ("W", 270)]:
            a = math.radians(ang - 90)
            lx = cx2 + math.cos(a)*(r2+10)
            ly = cy2 + math.sin(a)*(r2+10)
            p.setFont(QFont("Arial", 8)); p.setPen(QPen(GREY))
            p.drawText(int(lx-8), int(ly-6), 16, 12, Qt.AlignHCenter, lbl)

        wdir = self.state.wind_dir
        na = math.radians(wdir - 90)
        nx = cx2 + math.cos(na)*(r2-5)
        ny = cy2 + math.sin(na)*(r2-5)
        p.setPen(QPen(ORANGE, 4))
        p.drawLine(int(cx2), int(cy2), int(nx), int(ny))
        p.setBrush(QBrush(ORANGE)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx2, cy2), 4, 4)

        p.setFont(QFont("Arial", 8)); p.setPen(QPen(WHITE))
        p.drawText(int(cx2-30), int(cy2+r2+24), 60, 14, Qt.AlignHCenter,
                   f"{self.state.wind_display} {self.state.wind_unit}")

        return y + 150

    # ── Wind & gust scale ─────────────────────────────────────────────────────
    def _draw_wind_gust_scale(self, p, y):
        unit = self.state.wind_unit
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y, 250, 14, Qt.AlignLeft, f"wind and gust, {unit}")

        if self.state.metric:
            max_v = 90
            ticks = [(t, str(t)) for t in [5, 10, 15, 20, 30, 40, 50, 60, 80]]
        else:
            max_v = 55
            ticks = [(t, str(t)) for t in [2, 4, 6, 8, 10, 15, 20, 25, 30, 40, 50]]

        W = CANVAS_W
        scale_w = W - 40
        rect = QRectF(20, y + 22, scale_w, 28)
        draw_tick_scale(p, rect, 0, max_v, self.state.wind_display, ticks, CYAN)

        frac = min(1.0, self.state.gust_display / max_v)
        gx = 20 + frac * scale_w
        gy = y + 30
        gp = QPainterPath()
        gp.moveTo(gx, gy); gp.lineTo(gx-4, gy-8); gp.lineTo(gx+4, gy-8)
        gp.closeSubpath()
        p.fillPath(gp, ORANGE)

        return y + 55

    # ── Barometric pressure + Moon ────────────────────────────────────────────
    def _draw_pressure_moon(self, p, y):
        W = CANVAS_W
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y, 160, 14, Qt.AlignLeft, "barometric pressure")
        p.drawText(10, y, W - 14, 14, Qt.AlignRight, "moon phase")

        p.setFont(QFont("Arial", 10)); p.setPen(QPen(CYAN))
        p.drawText(10, y+15, 16, 20, Qt.AlignLeft, "↓")
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(24, y+20, 50, 14, Qt.AlignLeft, "falling")

        p.setFont(QFont("Arial", 14, QFont.Bold)); p.setPen(QPen(WHITE))
        pval = self.state.pressure_display
        fmt = f"{pval:.1f}" if self.state.metric else f"{pval:.2f}"
        p.drawText(10, y+30, 130, 22, Qt.AlignLeft, fmt)
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y+50, 80, 12, Qt.AlignLeft, self.state.pressure_unit)

        known_new = 1704854400  # 2024-01-11 11:57 UTC — verified new moon
        lunar_period = 29.530589 * 86400
        raw_frac = ((time.time() - known_new) % lunar_period) / lunar_period
        illum = (1 - math.cos(raw_frac * 2 * math.pi)) / 2

        if raw_frac < 0.025 or raw_frac >= 0.975:
            phase_name = "New Moon"
        elif raw_frac < 0.25:
            phase_name = "Waxing Crescent"
        elif raw_frac < 0.275:
            phase_name = "First Quarter"
        elif raw_frac < 0.50:
            phase_name = "Waxing Gibbous"
        elif raw_frac < 0.525:
            phase_name = "Full Moon"
        elif raw_frac < 0.75:
            phase_name = "Waning Gibbous"
        elif raw_frac < 0.775:
            phase_name = "Third Quarter"
        else:
            phase_name = "Waning Crescent"

        moon_dots, dot_r, gap = 16, 4, 3
        span_total = moon_dots * (dot_r*2+gap) - gap
        mx = W - span_total - 14
        moy = y + 35
        for i in range(moon_dots):
            active = (i / moon_dots) < raw_frac
            p.setBrush(QBrush(YELLOW if active else DIM)); p.setPen(Qt.NoPen)
            cx = mx + i * (dot_r*2+gap) + dot_r
            p.drawEllipse(QPointF(cx, moy), dot_r, dot_r)

        span = span_total
        p.setPen(QPen(GREY)); p.setFont(QFont("Arial", 6))
        for lbl, frac in [("new", 0.0), ("full", 0.5), ("new", 1.0)]:
            lx = mx + frac * span
            p.drawText(int(lx-10), int(moy+12), 20, 12, Qt.AlignHCenter, lbl)

        p.setFont(QFont("Arial", 6, QFont.Bold)); p.setPen(QPen(YELLOW))
        p.drawText(mx - 2, int(moy+24), int(span+dot_r), 12,
                   Qt.AlignHCenter, f"{phase_name}  {illum*100:.0f}%")

        return y + 84

    # ── Temperature dot bar ───────────────────────────────────────────────────
    def _draw_temp_bar(self, p, y):
        unit = self.state.temp_unit
        p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
        p.drawText(10, y, 200, 14, Qt.AlignLeft, f"temperature, {unit}")

        if self.state.metric:
            temp_stops = [-20, -10, 0, 10, 20, 25, 30, 35, 40, 45]
        else:
            temp_stops = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

        W = CANVAS_W
        n = len(temp_stops)
        dot_r, gap = 10, 4
        total_w = n * (dot_r * 2 + gap) - gap
        ox = (W - total_w) // 2
        oy = y + 32
        temp = self.state.temp_display
        t_min, t_max = temp_stops[0], temp_stops[-1]

        for i, tv in enumerate(temp_stops):
            frac = (tv - t_min) / (t_max - t_min)
            if frac < 0.25:
                c = QColor(0x44, 0x88, 0xff)
            elif frac < 0.5:
                c = QColor(0x00, 0xdd, 0xcc)
            elif frac < 0.75:
                c = YELLOW
            else:
                c = PINK

            step = (t_max - t_min) / (n - 1)
            active = temp >= tv - step * 0.5
            cx = ox + i * (dot_r*2+gap) + dot_r
            p.setBrush(QBrush(c if active else DIM)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, oy), dot_r, dot_r)

            p.setFont(QFont("Arial", 7)); p.setPen(QPen(GREY))
            p.drawText(int(cx-10), int(oy+dot_r+4), 20, 12,
                       Qt.AlignHCenter, str(tv))

        p.setFont(QFont("Arial", 13, QFont.Bold)); p.setPen(QPen(WHITE))
        p.drawText(0, int(oy+dot_r+22), W, 20, Qt.AlignHCenter,
                   f"Current: {temp:.1f}{unit}")


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════
def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    app = QApplication(sys.argv)
    app.setOverrideCursor(Qt.BlankCursor)

    state = WeatherState()

    # demo seed values — replaced immediately when real UDP data arrives
    state.wind_ms            = 4.0
    state.gust_ms            = 6.9
    state.wind_dir           = 225
    state.temp_c             = 18.5
    state.humidity           = 62.0
    state.pressure_mb        = 1012.5
    state.precip_rate_mmhr   = 0.0
    state.precip_mm          = 3.0
    state.uv_index           = 3.0
    state.conditions         = "partly"
    state.forecast_hour_dots = [0.1, 0.2, 0.3, 0.5, 0.7, 0.8,
                                 0.6, 0.4, 0.2, 0.1, 0.1, 0.05]

    widget = TempestWidget(state)

    listener = TempestListener()
    listener.data_received.connect(lambda msg: (state.ingest(msg), widget.update()))
    listener.start()

    timer = QTimer()
    timer.timeout.connect(widget.update)
    timer.start(1000)

    widget.showFullScreen()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
