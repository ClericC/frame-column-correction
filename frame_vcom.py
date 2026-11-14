#!/usr/bin/env python3
# Copyright (c) 2026 ClericC - MIT License - https://github.com/ClericC/frame-column-correction
"""Column Correction (Frame VCOM) - a SteamVR dashboard app for the vcom-fix column-correction service on the Steam Frame.

The app never touches the displays itself: it only edits /home/steamos/vcom-fix/vcom.conf.
The root service vcom-fix reads that file, applies the VCOM values and reports back in /run/vcom-fix.state.

Usage:
  frame_vcom.py                 run as a SteamVR dashboard overlay
  frame_vcom.py --preview DIR   render sample screens as PNG files (no SteamVR needed)
"""
import ctypes
import json
import math
import os
import struct
import sys
import time
import zlib

HERE = os.path.dirname(os.path.realpath(__file__))
CONF = os.environ.get("VCOM_CONF", "/home/steamos/vcom-fix/vcom.conf")
STATE = os.environ.get("VCOM_STATE", "/run/vcom-fix.state")
SETTINGS = os.environ.get("VCOM_SETTINGS", os.path.expanduser("~/.config/frame-vcom/settings.json"))
W, H = 1024, 768
TRIM_MAX = 45         # same as the service's overall limit, so one trim can reach any value
MIN_GAP = 3           # degrees between the cold and the hot calibration point
STALE_S = 10          # service state older than this counts as "not running"
CONFIRM_S = 4         # seconds a "press again to confirm" stays armed
UNDO_S = 20           # seconds the "Undo" button stays after saving a point
TEMP_REDRAW_S = 30    # temperatures alone redraw the panel at most this often (every upload blinks)
LAG_MIN_MIN, LAG_MIN_MAX, LAG_DEFAULT = 5, 60, 22
GHOST_S = 300         # ghosting test: seconds of the static pattern before the grey check

# ------------------------------------------------------------------ texts

TEXT = {
    "en": {
        "title": "Column Correction",
        "on": "ON", "off": "OFF",
        "camera": "Cameras", "display": "Displays (est.)",
        "left": "Left display", "right": "Right display",
        "detail": "curve {curve}  ·  trim {trim}",
        "reset": "Reset",
        "calib": "Calibration: save the current values as a curve point",
        "save_cold": "Save cold point", "save_hot": "Save hot point",
        "point": "saved: {t} °C → {l} / {r}",
        "confirm": "Press again to save at {t} °C",
        "undo": "Undo",
        "close": "Close",
        "tools": "Calibration tools",
        "stale": "Service vcom-fix is not responding",
        "no_factory": "Cannot read the displays' factory values",
        "unknown_driver": "Unknown display driver: correction paused",
        "disabled_note": "Off: factory values",
        "pat_title": "Test pattern",
        "pat_hint": "A flat background in front of you: stripes are easiest to see on it.",
        "grey": "Grey", "green": "Green", "blue": "Blue", "ghost": "Ghosting",
        "pat_off": "Remove pattern",
        "pat_exit": "Close the dashboard and turn your head slowly.",
        "ghost_hint": "Ghosting: 5 minutes of a pattern, then a grey background.",
        "lag_title": "Display warm-up delay (LAG_MIN)",
        "lag_val": "{m} min", "lag_default": "default {m}",
        "lag_less": "Lower it if the correction lags behind during warm-up.",
        "lag_more": "Raise it if it runs ahead (\"inverted\" stripes).",
        "back": "Back",
        "pat_caption": "Test pattern · turn your head slowly · remove it in the app",
        "ghost_caption": "Ghosting test: {m} min left",
        "ghost_check": "Close one eye, then the other. Does an outline stay for more than a few seconds?",
        "m_saved_cold": "Cold point saved: {t} °C → {l} / {r}",
        "m_saved_hot": "Hot point saved: {t} °C → {l} / {r}",
        "m_undone": "Undone: the previous point is back",
        "m_too_warm": "Too warm for the cold point (needs ≤ {t} °C)",
        "m_too_cold": "Too cold for the hot point (needs ≥ {t} °C)",
        "m_need_on": "Turn the correction on first",
        "m_no_data": "No data from the vcom-fix service",
        "m_write_err": "Could not save the settings: {e}",
        "m_trim_limit": "Trim limit: ±{m}",
    },
    "de": {
        "title": "Column Correction",
        "on": "AN", "off": "AUS",
        "camera": "Kameras", "display": "Displays (geschätzt)",
        "left": "Linkes Display", "right": "Rechtes Display",
        "detail": "Kurve {curve}  ·  Korrektur {trim}",
        "reset": "Zurücksetzen",
        "calib": "Kalibrierung: aktuelle Werte als Kurvenpunkt speichern",
        "save_cold": "Kaltpunkt speichern", "save_hot": "Warmpunkt speichern",
        "point": "gespeichert: {t} °C → {l} / {r}",
        "confirm": "Nochmal: bei {t} °C speichern",
        "undo": "Rückgängig",
        "close": "Schließen",
        "tools": "Kalibrierwerkzeuge",
        "stale": "Dienst vcom-fix antwortet nicht",
        "no_factory": "Werkswerte der Displays nicht lesbar",
        "unknown_driver": "Unbekannter Displaytreiber: Korrektur pausiert",
        "disabled_note": "Aus: Werkseinstellung",
        "pat_title": "Testbild",
        "pat_hint": "Gleichmäßige Fläche vor Ihnen: darauf sind Streifen gut sichtbar.",
        "grey": "Grau", "green": "Grün", "blue": "Blau", "ghost": "Nachbilder",
        "pat_off": "Testbild entfernen",
        "pat_exit": "Dashboard schließen und den Kopf langsam drehen.",
        "ghost_hint": "Nachbilder: 5 Minuten Muster, dann eine graue Fläche.",
        "lag_title": "Aufwärmverzögerung der Displays (LAG_MIN)",
        "lag_val": "{m} Min.", "lag_default": "Standard {m}",
        "lag_less": "Verringern, wenn die Korrektur beim Aufwärmen nachhinkt.",
        "lag_more": "Erhöhen, wenn sie vorauseilt („umgekehrte“ Streifen).",
        "back": "Zurück",
        "pat_caption": "Testbild · Kopf langsam drehen · in der App entfernen",
        "ghost_caption": "Nachbildtest: noch {m} Min.",
        "ghost_check": "Ein Auge schließen, dann das andere. Bleibt ein Umriss länger als ein paar Sekunden?",
        "m_saved_cold": "Kaltpunkt gespeichert: {t} °C → {l} / {r}",
        "m_saved_hot": "Warmpunkt gespeichert: {t} °C → {l} / {r}",
        "m_undone": "Rückgängig: vorheriger Punkt wiederhergestellt",
        "m_too_warm": "Zu warm für den Kaltpunkt (höchstens {t} °C)",
        "m_too_cold": "Zu kalt für den Warmpunkt (mindestens {t} °C)",
        "m_need_on": "Zuerst die Korrektur einschalten",
        "m_no_data": "Keine Daten vom Dienst vcom-fix",
        "m_write_err": "Einstellungen nicht gespeichert: {e}",
        "m_trim_limit": "Korrekturgrenze: ±{m}",
    },
    "ru": {
        "title": "Коррекция столбцов",
        "on": "ВКЛ", "off": "ВЫКЛ",
        "camera": "Камеры", "display": "Дисплеи (расчёт)",
        "left": "Левый дисплей", "right": "Правый дисплей",
        "detail": "кривая {curve}  ·  поправка {trim}",
        "reset": "Сброс",
        "calib": "Калибровка: сохранить текущие значения как точку кривой",
        "save_cold": "Сохранить холодную точку", "save_hot": "Сохранить горячую точку",
        "point": "сохранено: {t} °C → {l} / {r}",
        "confirm": "Ещё раз — сохранить при {t} °C",
        "undo": "Отменить",
        "close": "Закрыть",
        "tools": "Инструменты калибровки",
        "stale": "Служба vcom-fix не отвечает",
        "no_factory": "Не удалось прочитать заводские значения дисплеев",
        "unknown_driver": "Неизвестный драйвер дисплеев: коррекция приостановлена",
        "disabled_note": "Выключено: заводские значения",
        "pat_title": "Тестовая картинка",
        "pat_hint": "Ровный фон перед глазами: на нём полосы видно лучше всего.",
        "grey": "Серый", "green": "Зелёный", "blue": "Синий", "ghost": "«Призраки»",
        "pat_off": "Убрать картинку",
        "pat_exit": "Закройте дашборд и медленно поворачивайте голову.",
        "ghost_hint": "«Призраки»: 5 минут узор, затем серый фон.",
        "lag_title": "Задержка прогрева дисплеев (LAG_MIN)",
        "lag_val": "{m} мин", "lag_default": "по умолчанию {m}",
        "lag_less": "Уменьшить — если при прогреве коррекция запаздывает.",
        "lag_more": "Увеличить — если опережает (полосы «наоборот»).",
        "back": "Назад",
        "pat_caption": "Тестовая картинка · медленно поворачивайте голову · убрать — в приложении",
        "ghost_caption": "Тест на «призраки»: осталось {m} мин",
        "ghost_check": "Закройте один глаз, затем другой. Контур виден дольше нескольких секунд?",
        "m_saved_cold": "Холодная точка сохранена: {t} °C → {l} / {r}",
        "m_saved_hot": "Горячая точка сохранена: {t} °C → {l} / {r}",
        "m_undone": "Отменено: прежняя точка восстановлена",
        "m_too_warm": "Слишком тепло для холодной точки (нужно ≤ {t} °C)",
        "m_too_cold": "Слишком холодно для горячей точки (нужно ≥ {t} °C)",
        "m_need_on": "Сначала включите коррекцию",
        "m_no_data": "Нет данных от службы vcom-fix",
        "m_write_err": "Не удалось сохранить настройки: {e}",
        "m_trim_limit": "Предел поправки: ±{m}",
    },
}
LANGS = ("en", "de", "ru")
PATTERN_COLOURS = {"grey": (128, 128, 128), "green": (60, 140, 40), "blue": (50, 80, 160)}


def sgn(v):
    """+5 / −3 / 0 with a real minus sign."""
    if not isinstance(v, int):
        return "—"
    return f"+{v}" if v > 0 else (f"−{-v}" if v < 0 else "0")


# ------------------------------------------------------------------ files


def read_kv(path):
    """key=value file -> dict; integer values become int. Missing file -> {}."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                try:
                    out[k] = int(v)
                except ValueError:
                    out[k] = v
    except OSError:
        pass
    return out


def update_conf(path, changes):
    """Replace or add KEY=value lines, keep everything else; written atomically."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in changes:
            lines[i] = f"{key}={int(changes[key])}"
            done.add(key)
    lines += [f"{k}={int(v)}" for k, v in changes.items() if k not in done]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            s = json.load(f)
        if s.get("lang") in TEXT:
            return s
    except (OSError, ValueError):
        pass
    lang = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "")
    code = lang.lower()[:2]
    return {"lang": code if code in TEXT else "en"}  # first start: the system language, else English


def save_settings(s):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except OSError:
        pass


def state_fresh(state, now=None):
    now = time.time() if now is None else now
    return isinstance(state.get("updated"), int) and now - state["updated"] <= STALE_S


def est_temp(state):
    """Display temperature estimate in whole degrees, or None."""
    v = state.get("display_est_mc")
    return int(round(v / 1000)) if isinstance(v, int) else None


# ------------------------------------------------------------------ actions (pure logic, unit-tested)


def trim_change(conf, side, delta):
    """New trim value for 'left'/'right' after +-delta (delta 0 = reset). Returns (changes, msg)."""
    key = "LEFT_TRIM" if side == "left" else "RIGHT_TRIM"
    cur = conf.get(key, 0) if isinstance(conf.get(key, 0), int) else 0
    if delta == 0:
        return {key: 0}, None
    new = cur + delta
    if new > TRIM_MAX or new < -TRIM_MAX:
        return {}, ("m_trim_limit", {"m": TRIM_MAX})
    return {key: new}, None


def lag_change(conf, delta):
    """New LAG_MIN after +-delta, kept within LAG_MIN_MIN..LAG_MIN_MAX."""
    cur = conf.get("LAG_MIN", LAG_DEFAULT)
    cur = cur if isinstance(cur, int) else LAG_DEFAULT
    new = max(LAG_MIN_MIN, min(LAG_MIN_MAX, cur + delta))
    return {"LAG_MIN": new} if new != cur else {}


def save_point(kind, conf, state):
    """Store the currently applied offsets at the current display temperature as the cold or hot point.
    The trims are folded into the point and reset, so the output does not jump. Returns (changes, msg)."""
    if not state_fresh(state) or state.get("error") or not isinstance(state.get("display_est_mc"), int):
        return {}, ("m_no_data", {})
    if state.get("enabled") != 1:
        return {}, ("m_need_on", {})
    t = est_temp(state)
    left, right = state.get("left", 0), state.get("right", 0)
    if kind == "cold":
        limit = conf.get("HOT_TEMP", 52) - MIN_GAP
        if t > limit:
            return {}, ("m_too_warm", {"t": limit})
        changes = {"COLD_TEMP": t, "COLD_LEFT": left, "COLD_RIGHT": right}
        if conf.get("HOT_LEFT", 0) == 0 and conf.get("HOT_RIGHT", 0) == 0:
            # no hot point yet: keep the curve flat at the cold values instead of sloping back to 0
            changes.update({"HOT_LEFT": left, "HOT_RIGHT": right})
    else:
        limit = conf.get("COLD_TEMP", 34) + MIN_GAP
        if t < limit:
            return {}, ("m_too_cold", {"t": limit})
        changes = {"HOT_TEMP": t, "HOT_LEFT": left, "HOT_RIGHT": right}
    changes.update({"LEFT_TRIM": 0, "RIGHT_TRIM": 0})
    return changes, ("m_saved_" + kind, {"t": t, "l": sgn(left), "r": sgn(right)})


DEFAULTS = {"COLD_TEMP": 34, "HOT_TEMP": 52, "LAG_MIN": LAG_DEFAULT}


def undo_values(conf, changes):
    """The values to restore if the given changes are undone."""
    return {k: conf.get(k, DEFAULTS.get(k, 0)) if isinstance(conf.get(k, 0), int) else DEFAULTS.get(k, 0)
            for k in changes}


# ------------------------------------------------------------------ drawing

BG = (20, 23, 29)
CARD = (31, 36, 44)
HEAD = (26, 30, 37)
FG = (232, 236, 241)
DIM = (139, 149, 163)
GOOD = (120, 200, 130)
WARN = (235, 180, 80)
BAD = (230, 115, 105)
BTN = (48, 55, 66)
ACCENT = (79, 163, 255)
ACCENT_DARK = (10, 30, 55)
CAPTION = (30, 34, 41)


class Glyphs:
    def __init__(self, folder):
        with open(os.path.join(folder, "glyphs.json"), encoding="utf-8") as f:
            self.meta = json.load(f)
        with open(os.path.join(folder, "glyphs.bin"), "rb") as f:
            self.blob = f.read()
        self.cache = {}

    def width(self, text, font):
        g = self.meta[font]["glyphs"]
        return sum(g.get(str(ord(c)), g["63"])[4] for c in text)

    def rows(self, ch, font, fg, bg):
        """Rows of RGBA bytes for one glyph, blended once onto a solid background colour."""
        key = (ch, font, fg, bg)
        if key not in self.cache:
            g = self.meta[font]["glyphs"]
            w, h, x0, y0, _, off = g.get(str(ord(ch)), g["63"])
            alpha = self.blob[off:off + w * h]
            lut = [bytes((bg[0] + (fg[0] - bg[0]) * a // 255, bg[1] + (fg[1] - bg[1]) * a // 255,
                          bg[2] + (fg[2] - bg[2]) * a // 255, 255)) for a in range(256)]
            rows = [b"".join(lut[a] for a in alpha[y * w:(y + 1) * w]) for y in range(h)]
            self.cache[key] = (w, h, x0, y0, rows)
        return self.cache[key]


class Canvas:
    def __init__(self, glyphs, w=W, h=H):
        self.g = glyphs
        self.w, self.h = w, h
        self.px = bytearray(w * h * 4)

    def fill(self, x0, y0, x1, y1, col):
        x0, x1 = max(0, x0), min(self.w, x1)
        y0, y1 = max(0, y0), min(self.h, y1)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes((col[0], col[1], col[2], 255)) * (x1 - x0)
        for y in range(y0, y1):
            o = (y * self.w + x0) * 4
            self.px[o:o + len(row)] = row

    def text(self, s, x, baseline, font, fg, bg, align="left"):
        if align != "left":
            w = self.g.width(s, font)
            x -= w // 2 if align == "center" else w
        g = self.g.meta[font]["glyphs"]
        for ch in s:
            w, h, x0, y0, rows = self.g.rows(ch, font, fg, bg)
            gx, gy = x + x0, baseline + y0
            for i, row in enumerate(rows):
                y = gy + i
                if 0 <= y < self.h and 0 <= gx and gx + w <= self.w:
                    o = (y * self.w + gx) * 4
                    self.px[o:o + len(row)] = row
            x += g.get(str(ord(ch)), g["63"])[4]

    def text_mid(self, s, x0, y0, x1, y1, font, fg, bg):
        """Text centred in a box (vertically by the cap height)."""
        m = self.g.meta[font]
        cap = m["ascent"] * 0.72
        self.text(s, (x0 + x1) // 2, int((y0 + y1) / 2 + cap / 2), font, fg, bg, "center")

    def png(self):
        w, h = self.w, self.h
        raw = b"".join(b"\x00" + bytes(self.px[y * w * 4:(y + 1) * w * 4]) for y in range(h))
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# Test patterns: separate overlays in front of the user (1024 x 512 textures)
PW, PH = 1024, 512
GHOST_TEXT_Y = 120   # caption baseline on both ghosting screens (the texture edges are outside the view)


def wrap(g, text, font, maxw):
    """Split a text into lines no wider than maxw."""
    sep = " · " if " · " in text else " "   # prefer breaking between the parts of a caption
    lines, cur = [], ""
    for word in text.split(sep):
        test = (cur + sep + word) if cur else word
        if cur and g.width(test, font) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = test
    return lines + [cur] if cur else lines


def caption_strip(c, text, y, col=FG, up=True, font="s"):
    """A dark strip with centred text; y is the baseline of the first line (up: of the last line)."""
    m = c.g.meta[font]
    lh = m["ascent"] + m["descent"] + 6          # line height
    pad = lh // 3
    lines = wrap(c.g, text, font, c.w - 80)
    if up:
        y -= lh * (len(lines) - 1)
    w = min(c.w - 40, max(c.g.width(line, font) for line in lines) + 2 * lh)
    c.fill((c.w - w) // 2, y - m["ascent"] - pad, (c.w + w) // 2, y + m["descent"] + pad + lh * (len(lines) - 1), CAPTION)
    for i, line in enumerate(lines):
        c.text(line, c.w // 2, y + lh * i, font, col, CAPTION, "center")


def pattern_solid(glyphs, colour, caption):
    c = Canvas(glyphs, PW, PH)
    c.fill(0, 0, PW, PH, colour)
    caption_strip(c, caption, PH - 40)
    return c


def pattern_checker(glyphs, caption):
    c = Canvas(glyphs, PW, PH)
    sq = 64
    for y in range(0, PH, sq):
        for x in range(0, PW, sq):
            c.fill(x, y, x + sq, y + sq, (235, 235, 235) if (x // sq + y // sq) % 2 else (15, 15, 15))
    caption_strip(c, caption, GHOST_TEXT_Y, WARN, up=False)
    return c


def pattern_ghost_check(glyphs, question):
    c = Canvas(glyphs, PW, PH)
    c.fill(0, 0, PW, PH, (128, 128, 128))
    caption_strip(c, question, GHOST_TEXT_Y, up=False, font="xs")
    return c


# ------------------------------------------------------------------ the panel


class Panel:
    def __init__(self, glyphs):
        self.c = Canvas(glyphs)
        self.settings = load_settings()
        self.conf, self.state = {}, {}
        self.buttons = []           # (x0, y0, x1, y1, id)
        self.hover = None
        self.screen = "main"        # or "tools"
        self.armed = None           # (button id, until) for two-step buttons
        self.msg = None             # (key, args, colour, until)
        self.undo = None            # (values to restore, until)
        self.pattern = None         # None, "grey", "green", "blue", "ghost", "ghost_check"
        self.pattern_since = 0.0
        self.pattern_dirty = False  # the pattern overlay needs to be (re)built
        self.quit = False
        self.cut = []               # texts that had to be shortened (checked by the tests)

    @property
    def t(self):
        return TEXT[self.settings["lang"]]

    def _major(self):
        st = self.state
        return (self.conf, st.get("left"), st.get("right"), st.get("curve_left"), st.get("curve_right"),
                st.get("trim_left"), st.get("trim_right"), st.get("enabled"), st.get("error"), state_fresh(st))

    def refresh(self):
        """Re-read the files. Returns (major, minor): major = values/settings changed (redraw now),
        minor = only the temperatures changed (redraw rarely: every upload makes the panel blink)."""
        old_major, old_temps = self._major(), (self.state.get("display_est_mc"), self.state.get("camera_mc"))
        self.conf, self.state = read_kv(CONF), read_kv(STATE)
        temps = (self.state.get("display_est_mc"), self.state.get("camera_mc"))
        return self._major() != old_major, temps != old_temps

    def tick(self, now):
        """Expire timed UI elements and advance the ghosting test; True if the panel needs a redraw."""
        changed = False
        if self.armed and now > self.armed[1]:
            self.armed, changed = None, True
        if self.msg and now > self.msg[3]:
            self.msg, changed = None, True
        if self.undo and now > self.undo[1]:
            self.undo, changed = None, True
        if self.pattern == "ghost":
            if now - self.pattern_since >= GHOST_S:
                self.pattern, self.pattern_since, self.pattern_dirty = "ghost_check", now, True
            elif self.ghost_minutes_left(now) != getattr(self, "_ghost_shown", None):
                self.pattern_dirty = True   # update the countdown once a minute
        return changed

    def ghost_minutes_left(self, now):
        return max(1, math.ceil((GHOST_S - (now - self.pattern_since)) / 60))

    def pattern_canvas(self, now=None):
        """The texture for the current test pattern, or None."""
        now = time.time() if now is None else now
        t, g = self.t, self.c.g
        if self.pattern in PATTERN_COLOURS:
            return pattern_solid(g, PATTERN_COLOURS[self.pattern], t["pat_caption"])
        if self.pattern == "ghost":
            self._ghost_shown = self.ghost_minutes_left(now)
            return pattern_checker(g, t["ghost_caption"].format(m=self._ghost_shown))
        if self.pattern == "ghost_check":
            return pattern_ghost_check(g, t["ghost_check"])
        return None

    def say(self, msg, ok=True):
        if msg:
            key, args = msg
            self.msg = (key, args, GOOD if ok else WARN, time.time() + 6)

    def apply(self, changes):
        if not changes:
            return True
        try:
            update_conf(CONF, changes)
            self.conf = read_kv(CONF)
            return True
        except OSError as e:
            self.msg = ("m_write_err", {"e": e.strerror or str(e)}, BAD, time.time() + 8)
            return False

    def set_pattern(self, name):
        self.pattern, self.pattern_since, self.pattern_dirty = name, time.time(), True

    def click(self, bid):
        now = time.time()
        if bid in ("save_cold", "save_hot"):
            if not (self.armed and self.armed[0] == bid and now <= self.armed[1]):
                self.armed = (bid, now + CONFIRM_S)
                return
            self.armed = None
            changes, msg = save_point("cold" if bid == "save_cold" else "hot", self.conf, read_kv(STATE))
            before = undo_values(self.conf, changes)
            if self.apply(changes):
                self.say(msg, ok=bool(changes))
                if changes:
                    self.undo = (before, now + UNDO_S)
        elif bid == "undo" and self.undo:
            if self.apply(self.undo[0]):
                self.undo = None
                self.say(("m_undone", {}))
        elif bid == "toggle":
            self.apply({"ENABLED": 0 if self.conf.get("ENABLED", 0) == 1 else 1})
        elif bid.startswith("trim_"):
            _, side, op = bid.split("_")
            changes, msg = trim_change(self.conf, side, {"minus": -1, "plus": 1, "reset": 0}[op])
            if self.apply(changes):
                self.say(msg, ok=False)
        elif bid in ("lag_minus", "lag_plus"):
            self.apply(lag_change(self.conf, -1 if bid == "lag_minus" else 1))
        elif bid.startswith("pat_"):
            name = bid[4:]
            if name == "off":
                self.set_pattern(None)
            elif name in PATTERN_COLOURS or name == "ghost":
                self.set_pattern(name)
        elif bid == "tools":
            self.screen = "tools"
        elif bid == "back":
            self.screen = "main"
        elif bid.startswith("lang_") and bid[5:] in TEXT:
            self.settings["lang"] = bid[5:]
            save_settings(self.settings)
            if self.pattern:
                self.pattern_dirty = True   # captions follow the language
        elif bid == "close":
            self.quit = True

    def hit(self, x, y):
        for x0, y0, x1, y1, bid in self.buttons:
            if x0 <= x < x1 and y0 <= y < y1:
                return bid
        return None

    # -------------------------------------------------------------- render

    def fit(self, text, font, maxw):
        """Cut a text that is too wide and end it with an ellipsis."""
        if self.c.g.width(text, font) <= maxw:
            return text
        self.cut.append(text)
        while text and self.c.g.width(text + "…", font) > maxw:
            text = text[:-1]
        return text.rstrip() + "…"

    def button(self, x0, y0, x1, y1, bid, label, font="m", base=BTN, fg=FG):
        for smaller in ("m", "s"):  # shrink a label only if it does not fit
            if self.c.g.width(label, font) <= x1 - x0 - 20:
                break
            font = smaller
        self.c.fill(x0, y0, x1, y1, base)
        self.c.text_mid(self.fit(label, font, x1 - x0 - 12), x0, y0, x1, y1, font, fg, base)
        self.buttons.append((x0, y0, x1, y1, bid))

    def footer(self, left_buttons):
        c, t = self.c, self.t
        c.fill(0, 682, W, H, HEAD)
        x = 24
        for bid, label, width in left_buttons:
            self.button(x, 700, x + width, 750, bid, label, "s")
            x += width + 16
        lang = self.settings["lang"]
        for j, code in enumerate(LANGS):
            x0 = 744 + j * 82
            sel = code == lang
            self.button(x0, 700, x0 + 76, 750, "lang_" + code, code.upper(), "mb" if sel else "m",
                        base=ACCENT if sel else BTN, fg=ACCENT_DARK if sel else FG)

    def render(self):
        self.buttons = []
        if self.screen == "tools":
            return self.render_tools()
        c, t, st, cf = self.c, self.t, self.state, self.conf
        fresh = state_fresh(st)
        applied = fresh and not st.get("error")   # the service really writes the values
        enabled = cf.get("ENABLED", 0) == 1
        c.fill(0, 0, W, H, BG)

        # header
        c.fill(0, 0, W, 96, HEAD)
        c.text(t["title"], 40, 62, "l", FG, HEAD)
        self.button(824, 20, 984, 76, "toggle", t["on"] if enabled else t["off"], "mb",
                    base=ACCENT if enabled else BTN, fg=ACCENT_DARK if enabled else FG)

        # temperatures / service state
        err = st.get("error")
        if fresh and err in ("no_factory_values", "unknown_driver"):
            key = "no_factory" if err == "no_factory_values" else "unknown_driver"
            f = "m" if c.g.width(t[key], "m") <= W - 80 else "s"
            c.text(self.fit(t[key], f, W - 80), W // 2, 150, f, BAD, BG, "center")
        elif fresh:
            cam, est = st.get("camera_mc"), st.get("display_est_mc")
            fmt = lambda v: f"{v / 1000:.1f} °C" if isinstance(v, int) else "—"
            c.text(f"{t['camera']}  {fmt(cam)}", 40, 150, "m", DIM, BG)
            c.text(f"{t['display']}  {fmt(est)}", 984, 150, "m", FG, BG, "right")
        else:
            c.text(t["stale"], W // 2, 150, "m", BAD, BG, "center")

        # display cards
        for i, side in enumerate(("left", "right")):
            x0 = 40 + i * 487
            x1 = x0 + 457
            c.fill(x0, 182, x1, 480, CARD)
            c.text(t[side], x0 + 28, 226, "mb", FG, CARD)
            if applied and enabled:
                val, curve = st.get(side, 0), st.get("curve_" + side, 0)
                trim = st.get("trim_" + side, 0)
                c.text(sgn(val), (x0 + x1) // 2, 340, "xl", FG, CARD, "center")
                c.text(t["detail"].format(curve=sgn(curve), trim=sgn(trim)), (x0 + x1) // 2, 386, "s", DIM, CARD,
                       "center")
            elif applied:
                c.text("0", (x0 + x1) // 2, 340, "xl", DIM, CARD, "center")
                c.text(t["disabled_note"], (x0 + x1) // 2, 386, "s", DIM, CARD, "center")
            else:
                c.text("—", (x0 + x1) // 2, 340, "xl", DIM, CARD, "center")
            by0, by1 = 408, 462
            self.button(x0 + 24, by0, x0 + 124, by1, f"trim_{side}_minus", "−", "l")
            self.button(x0 + 138, by0, x1 - 138, by1, f"trim_{side}_reset", t["reset"], "m")
            self.button(x1 - 124, by0, x1 - 24, by1, f"trim_{side}_plus", "+", "l")

        # calibration (a message, if any, temporarily takes the place of the caption; then "Undo" on the right)
        line_w = W - 80 - (200 if self.undo else 0)
        if self.msg:
            key, args, col, _ = self.msg
            c.text(self.fit(t[key].format(**args), "s", line_w), 40, 530, "s", col, BG)
        else:
            c.text(self.fit(t["calib"], "s", line_w), 40, 530, "s", DIM, BG)
        if self.undo:
            self.button(800, 498, 984, 540, "undo", t["undo"], "s", base=WARN, fg=ACCENT_DARK)
        cal_font = "m" if all(c.g.width(t[k], "m") <= 457 - 20 for k in ("save_cold", "save_hot")) else "s"
        temp = est_temp(st)
        for i, (bid, kind) in enumerate((("save_cold", "COLD"), ("save_hot", "HOT"))):
            x0 = 40 + i * 487
            x1 = x0 + 457
            armed = self.armed and self.armed[0] == bid
            label = t["confirm"].format(t=temp if temp is not None else "?") if armed else t["save_" + bid[5:]]
            self.button(x0, 548, x1, 612, bid, label, cal_font,
                        base=WARN if armed else BTN, fg=ACCENT_DARK if armed else FG)
            info = t["point"].format(t=cf.get(kind + "_TEMP", "?"), l=sgn(cf.get(kind + "_LEFT", 0)),
                                     r=sgn(cf.get(kind + "_RIGHT", 0)))
            c.text(info, (x0 + x1) // 2, 646, "s", DIM, BG, "center")

        self.footer((("close", t["close"], 160), ("tools", t["tools"], 400)))
        return c.px

    def render_tools(self):
        c, t, cf = self.c, self.t, self.conf
        c.fill(0, 0, W, H, BG)
        c.fill(0, 0, W, 96, HEAD)
        c.text(t["tools"], 40, 62, "l", FG, HEAD)

        # test patterns
        c.fill(40, 120, 984, 424, CARD)
        c.text(t["pat_title"], 68, 166, "mb", FG, CARD)
        c.text(self.fit(t["pat_hint"], "s", 888), 68, 204, "s", DIM, CARD)
        for i, name in enumerate(("grey", "green", "blue")):
            x0 = 68 + i * 214
            sel = self.pattern == name
            self.button(x0, 228, x0 + 196, 290, "pat_" + name, t[name], "mb" if sel else "m",
                        base=PATTERN_COLOURS[name], fg=(255, 255, 255) if sel else (235, 235, 235))
            if sel:
                c.fill(x0, 290, x0 + 196, 296, ACCENT)
        ghost_on = self.pattern in ("ghost", "ghost_check")
        self.button(710, 228, 956, 290, "pat_ghost", t["ghost"], "m", base=ACCENT if ghost_on else BTN,
                    fg=ACCENT_DARK if ghost_on else FG)
        c.text(self.fit(t["pat_exit"], "s", 888), 68, 336, "s", DIM, CARD)
        if self.pattern:
            self.button(68, 352, 420, 404, "pat_off", t["pat_off"], "m", base=WARN, fg=ACCENT_DARK)
        else:
            c.text(self.fit(t["ghost_hint"], "s", 888), 68, 378, "s", DIM, CARD)

        # LAG_MIN
        lag = cf.get("LAG_MIN", LAG_DEFAULT)
        lag = lag if isinstance(lag, int) else LAG_DEFAULT
        c.fill(40, 440, 984, 668, CARD)
        c.text(self.fit(t["lag_title"], "mb", 888), 68, 482, "mb", FG, CARD)
        self.button(68, 500, 188, 560, "lag_minus", "−", "l")
        c.text(t["lag_val"].format(m=lag), 330, 546, "l", FG, CARD, "center")
        self.button(472, 500, 592, 560, "lag_plus", "+", "l")
        c.text(t["lag_default"].format(m=LAG_DEFAULT), 620, 538, "s", DIM, CARD)
        c.text(self.fit(t["lag_less"], "s", 888), 68, 610, "s", DIM, CARD)
        c.text(self.fit(t["lag_more"], "s", 888), 68, 646, "s", DIM, CARD)

        self.footer((("back", t["back"], 160),))
        return c.px


# ------------------------------------------------------------------ OpenVR (C API through ctypes)

# Indices into the C function tables of OpenVR SDK v2.15.6 (IVROverlay_028 / IVRSystem_026),
# taken from openvr_capi.h with offsetof() for aarch64.
OV = {"CreateOverlay": 1, "DestroyOverlay": 3, "SetOverlayFlag": 11, "SetOverlaySortOrder": 20,
      "SetOverlayWidthInMeters": 22, "SetOverlayTransformAbsolute": 33,
      "SetOverlayTransformTrackedDeviceRelative": 35, "ShowOverlay": 43, "HideOverlay": 44,
      "PollNextOverlayEvent": 48, "SetOverlayInputMethod": 50, "SetOverlayMouseScale": 52, "SetOverlayRaw": 62,
      "SetOverlayFromFile": 63, "CreateDashboardOverlay": 67, "ShowDashboard": 72}
OV_LEN, SYS_LEN = 82, 51
SYS_GET_POSE, SYS_POLL, SYS_ACK_QUIT = 12, 30, 47
POSE_SIZE, POSE_VALID = 80, 76          # TrackedDevicePose_t: matrix at 0, bPoseIsValid at 76
EV_SIZE, EV_DATA = 60, 12
EV_MOUSE_MOVE, EV_MOUSE_DOWN, EV_MOUSE_UP, EV_FOCUS_LEAVE, EV_QUIT = 300, 301, 302, 304, 700
APP_OVERLAY, INPUT_MOUSE, FLAG_CLICK_STABILIZATION = 2, 1, 134217728
UNIVERSE_STANDING, HMD = 1, 0
KEY, PATTERN_KEY = b"frame.vcom", b"frame.vcom.pattern"
WORLD_DIST, WORLD_WIDTH = 2.0, 6.0      # world-fixed pattern: 2 m in front, 6 m wide (stripes need head motion)
HEAD_DIST, HEAD_WIDTH = 3.0, 6.0        # head-locked ghosting pattern: ~90 deg wide, behind the dashboard so it stays usable
U64, I32, U32 = ctypes.c_uint64, ctypes.c_int, ctypes.c_uint32


class Vec2(ctypes.Structure):
    _fields_ = [("v0", ctypes.c_float), ("v1", ctypes.c_float)]


def find_openvr():
    cands = [os.environ.get("VCOM_OPENVR_LIB", ""), "/opt/steamvr/bin/linuxarm64/libopenvr_api.so",
             os.path.expanduser("~/.local/share/Steam/steamapps/common/SteamVR/bin/linuxarm64/libopenvr_api.so")]
    for p in cands:
        if p and os.path.exists(p):
            return p
    raise SystemExit("libopenvr_api.so not found (is SteamVR installed?)")


def world_matrix(hmd):
    """3x4 row-major transform for a pattern WORLD_DIST in front of the headset, upright and facing it.
    hmd: the headset's 12 floats (row-major 3x4)."""
    px, py, pz = hmd[3], hmd[7], hmd[11]
    fx, fz = -hmd[2], -hmd[10]                  # forward = -Z axis of the headset, flattened
    n = math.hypot(fx, fz)
    fx, fz = (fx / n, fz / n) if n > 1e-6 else (0.0, -1.0)
    cx, cy, cz = px + WORLD_DIST * fx, py, pz + WORLD_DIST * fz
    xa, ya, za = (-fz, 0.0, fx), (0.0, 1.0, 0.0), (-fx, 0.0, -fz)   # right, up, towards the user
    return [xa[0], ya[0], za[0], cx, xa[1], ya[1], za[1], cy, xa[2], ya[2], za[2], cz]


class VR:
    def __init__(self):
        lib = self.lib = ctypes.CDLL(find_openvr())
        lib.VR_InitInternal2.restype = U32
        lib.VR_InitInternal2.argtypes = [ctypes.POINTER(I32), I32, ctypes.c_char_p]
        lib.VR_GetGenericInterface.restype = ctypes.c_void_p
        lib.VR_GetGenericInterface.argtypes = [ctypes.c_char_p, ctypes.POINTER(I32)]
        lib.VR_GetVRInitErrorAsEnglishDescription.restype = ctypes.c_char_p
        lib.VR_GetVRInitErrorAsEnglishDescription.argtypes = [I32]
        err = I32(0)
        lib.VR_InitInternal2(ctypes.byref(err), APP_OVERLAY, None)
        self.check(err, "VR_Init")
        self.ov = self.table(b"FnTable:IVROverlay_028", OV_LEN)
        self.sys = self.table(b"FnTable:IVRSystem_026", SYS_LEN)
        # a missing entry stays None instead of failing here; it only matters if that function is used
        f = lambda i, res, *a: ctypes.CFUNCTYPE(res, *a)(self.ov[i]) if self.ov[i] else None
        s = lambda i, res, *a: ctypes.CFUNCTYPE(res, *a)(self.sys[i]) if self.sys[i] else None
        P64, VP = ctypes.POINTER(U64), ctypes.c_void_p
        self.CreateDashboardOverlay = f(OV["CreateDashboardOverlay"], I32, ctypes.c_char_p, ctypes.c_char_p, P64, P64)
        self.CreateOverlay = f(OV["CreateOverlay"], I32, ctypes.c_char_p, ctypes.c_char_p, P64)
        self.DestroyOverlay = f(OV["DestroyOverlay"], I32, U64)
        self.SetOverlayFlag = f(OV["SetOverlayFlag"], I32, U64, I32, ctypes.c_bool)
        self.SetOverlaySortOrder = f(OV["SetOverlaySortOrder"], I32, U64, U32)
        self.SetOverlayWidthInMeters = f(OV["SetOverlayWidthInMeters"], I32, U64, ctypes.c_float)
        self.SetOverlayTransformAbsolute = f(OV["SetOverlayTransformAbsolute"], I32, U64, I32, VP)
        self.SetOverlayTransformTrackedDeviceRelative = f(OV["SetOverlayTransformTrackedDeviceRelative"], I32,
                                                          U64, U32, VP)
        self.ShowOverlay = f(OV["ShowOverlay"], I32, U64)
        self.HideOverlay = f(OV["HideOverlay"], I32, U64)
        self.PollNextOverlayEvent = f(OV["PollNextOverlayEvent"], ctypes.c_bool, U64, VP, U32)
        self.SetOverlayInputMethod = f(OV["SetOverlayInputMethod"], I32, U64, I32)
        self.SetOverlayMouseScale = f(OV["SetOverlayMouseScale"], I32, U64, ctypes.POINTER(Vec2))
        self.SetOverlayRaw = f(OV["SetOverlayRaw"], I32, U64, VP, U32, U32, U32)
        self.SetOverlayFromFile = f(OV["SetOverlayFromFile"], I32, U64, ctypes.c_char_p)
        self.ShowDashboard = f(OV["ShowDashboard"], None, ctypes.c_char_p)
        self.GetPose = s(SYS_GET_POSE, None, I32, ctypes.c_float, VP, U32)
        self.PollNextEvent = s(SYS_POLL, ctypes.c_bool, VP, U32)
        self.AcknowledgeQuit = s(SYS_ACK_QUIT, None)
        for name in ("CreateDashboardOverlay", "SetOverlayRaw", "PollNextOverlayEvent", "SetOverlayInputMethod",
                     "SetOverlayMouseScale", "DestroyOverlay", "PollNextEvent"):
            if getattr(self, name) is None:
                raise SystemExit(f"OpenVR function {name} is not available")
        self.handle = U64(0)
        self.pattern = None         # handle of the test-pattern overlay, created on first use
        self.dashboard = True

    def check(self, err, what):
        if err.value:
            msg = self.lib.VR_GetVRInitErrorAsEnglishDescription(err.value) or b""
            raise SystemExit(f"{what} failed: {err.value} {msg.decode(errors='replace')}")

    def table(self, name, n):
        err = I32(0)
        p = self.lib.VR_GetGenericInterface(name, ctypes.byref(err))
        self.check(err, name.decode())
        if not p:
            raise SystemExit(f"{name.decode()} not available")
        return ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p * n)).contents

    def create(self, name):
        """name: the dashboard tab title (UTF-8 bytes)."""
        thumb = U64(0)
        e = self.CreateDashboardOverlay(KEY, name, ctypes.byref(self.handle), ctypes.byref(thumb))
        if e == 0:
            if self.SetOverlayFromFile:
                self.SetOverlayFromFile(thumb, os.path.join(HERE, "icon.png").encode())
            if self.SetOverlayWidthInMeters:
                self.SetOverlayWidthInMeters(self.handle, 2.0)
        else:  # fallback: a panel 1.2 m in front of the headset
            print(f"CreateDashboardOverlay failed ({e}), using a plain overlay", flush=True)
            self.dashboard = False
            if not (self.CreateOverlay and self.ShowOverlay and self.SetOverlayTransformTrackedDeviceRelative):
                raise SystemExit("cannot create an overlay")
            e = self.CreateOverlay(KEY, name, ctypes.byref(self.handle))
            if e:
                raise SystemExit(f"CreateOverlay failed: {e}")
            m = (ctypes.c_float * 12)(1, 0, 0, 0, 0, 1, 0, -0.1, 0, 0, 1, -1.2)
            self.SetOverlayTransformTrackedDeviceRelative(self.handle, HMD, ctypes.cast(m, ctypes.c_void_p))
            self.SetOverlayWidthInMeters(self.handle, 1.0)
            self.ShowOverlay(self.handle)
        self.SetOverlayInputMethod(self.handle, INPUT_MOUSE)
        scale = Vec2(W, H)
        self.SetOverlayMouseScale(self.handle, ctypes.byref(scale))
        if self.SetOverlayFlag:
            self.SetOverlayFlag(self.handle, FLAG_CLICK_STABILIZATION, True)

    def raw(self, handle, px, w, h):
        buf = (ctypes.c_ubyte * len(px)).from_buffer(px)
        self.SetOverlayRaw(handle, ctypes.cast(buf, ctypes.c_void_p), w, h, 4)

    def upload(self, px):
        self.raw(self.handle, px, W, H)

    def hmd_pose(self):
        """The headset's 3x4 matrix as 12 floats, or None."""
        if not self.GetPose:
            return None
        buf = ctypes.create_string_buffer(POSE_SIZE)
        self.GetPose(UNIVERSE_STANDING, 0.0, buf, 1)
        if not buf.raw[POSE_VALID]:
            return None
        return list(struct.unpack_from("<12f", buf.raw, 0))

    def show_pattern(self, canvas, head_locked):
        """Show (or update) the test pattern; canvas None hides it."""
        if canvas is None:
            if self.pattern is not None and self.HideOverlay:
                self.HideOverlay(self.pattern)
            return
        if not (self.CreateOverlay and self.ShowOverlay and self.SetOverlayTransformTrackedDeviceRelative):
            return
        if self.pattern is None:
            h = U64(0)
            if self.CreateOverlay(PATTERN_KEY, b"Column Correction test pattern", ctypes.byref(h)):
                return
            self.pattern = h
        self.raw(self.pattern, canvas.px, canvas.w, canvas.h)
        pose = None if head_locked else self.hmd_pose()
        if pose is not None and self.SetOverlayTransformAbsolute:
            m = (ctypes.c_float * 12)(*world_matrix(pose))
            self.SetOverlayTransformAbsolute(self.pattern, UNIVERSE_STANDING, ctypes.cast(m, ctypes.c_void_p))
            width = WORLD_WIDTH
        else:   # head-locked (ghosting test), or no pose available
            m = (ctypes.c_float * 12)(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, -HEAD_DIST)
            self.SetOverlayTransformTrackedDeviceRelative(self.pattern, HMD, ctypes.cast(m, ctypes.c_void_p))
            width = HEAD_WIDTH
        if self.SetOverlayWidthInMeters:
            self.SetOverlayWidthInMeters(self.pattern, width)
        self.ShowOverlay(self.pattern)

    def shutdown(self):
        try:
            if self.pattern is not None:
                self.DestroyOverlay(self.pattern)
            self.DestroyOverlay(self.handle)
        finally:
            self.lib.VR_ShutdownInternal()


def run():
    panel = Panel(Glyphs(HERE))
    vr = VR()
    vr.create(panel.t["title"].encode("utf-8"))
    panel.refresh()
    vr.upload(panel.render())
    if vr.dashboard and vr.ShowDashboard:
        vr.ShowDashboard(KEY)
    ev = ctypes.create_string_buffer(EV_SIZE)
    pressed, next_read, last_draw = None, 0.0, time.time()
    print("Column Correction app running", flush=True)
    while not panel.quit:
        dirty = False
        while vr.PollNextEvent(ev, EV_SIZE):
            if struct.unpack_from("<I", ev.raw, 0)[0] == EV_QUIT:
                if vr.AcknowledgeQuit:
                    vr.AcknowledgeQuit()
                panel.quit = True
        while vr.PollNextOverlayEvent(vr.handle, ev, EV_SIZE):
            etype = struct.unpack_from("<I", ev.raw, 0)[0]
            if etype in (EV_MOUSE_MOVE, EV_MOUSE_DOWN, EV_MOUSE_UP):
                mx, my = struct.unpack_from("<ff", ev.raw, EV_DATA)
                bid = panel.hit(int(mx), int(H - my))  # mouse y is bottom-up
                if etype == EV_MOUSE_MOVE:
                    panel.hover = bid
                elif etype == EV_MOUSE_DOWN:
                    pressed = bid
                elif etype == EV_MOUSE_UP:
                    if bid and bid == pressed:
                        panel.click(bid)
                        dirty = True
                    pressed = None
            elif etype == EV_FOCUS_LEAVE:
                panel.hover = None
        now = time.time()
        if now >= next_read:
            major, minor = panel.refresh()
            dirty |= major or (minor and now - last_draw >= TEMP_REDRAW_S)
            next_read = now + 1.0
        if panel.tick(now) or (panel.pattern_dirty and panel.screen == "tools"):
            dirty = True
        if panel.pattern_dirty:
            panel.pattern_dirty = False
            vr.show_pattern(panel.pattern_canvas(now), head_locked=panel.pattern in ("ghost", "ghost_check"))
        if dirty and not panel.quit:
            vr.upload(panel.render())
            last_draw = now
        time.sleep(0.03)
    vr.shutdown()


# ------------------------------------------------------------------ preview (no SteamVR)


def preview(out):
    os.makedirs(out, exist_ok=True)
    panel = Panel(Glyphs(HERE))
    now = time.time()
    conf = {"COLD_TEMP": 34, "COLD_LEFT": 5, "COLD_RIGHT": 8, "HOT_TEMP": 52, "HOT_LEFT": 28, "HOT_RIGHT": 35,
            "LAG_MIN": 22, "LEFT_TRIM": 2, "RIGHT_TRIM": -1, "ENABLED": 1}
    state = {"enabled": 1, "camera_mc": 50300, "display_est_mc": 44100, "curve_left": 17, "curve_right": 22,
             "trim_left": 2, "trim_right": -1, "left": 19, "right": 21, "updated": int(now)}
    shots = [
        ("en_normal", "en", "main", conf, state, {}),
        ("de_normal", "de", "main", conf, state, {}),
        ("ru_normal", "ru", "main", conf, state, {}),
        ("en_confirm", "en", "main", conf, state, {"armed": ("save_hot", now + 9)}),
        ("ru_saved_undo", "ru", "main", conf, state,
         {"msg": ("m_saved_hot", {"t": 44, "l": "+19", "r": "+21"}, GOOD, now + 9), "undo": ({}, now + 9)}),
        ("de_off", "de", "main", dict(conf, ENABLED=0), dict(state, enabled=0, left=0, right=0), {}),
        ("en_stale", "en", "main", conf, dict(state, updated=int(now) - 60), {}),
        ("ru_unknown_driver", "ru", "main", conf, dict(state, error="unknown_driver"), {}),
        ("en_tools", "en", "tools", conf, state, {}),
        ("de_tools", "de", "tools", conf, state, {}),
        ("ru_tools", "ru", "tools", conf, state, {}),
        ("ru_tools_pattern_on", "ru", "tools", conf, state, {"pattern": "grey"}),
    ]
    for name, lang, screen, cf, st, extra in shots:
        panel.settings = {"lang": lang}
        panel.screen = screen
        panel.conf, panel.state = cf, st
        panel.armed, panel.msg, panel.undo = extra.get("armed"), extra.get("msg"), extra.get("undo")
        panel.pattern = extra.get("pattern")
        panel.render()
        with open(os.path.join(out, name + ".png"), "wb") as f:
            f.write(panel.c.png())
    for lang in LANGS:   # the test patterns themselves
        panel.settings = {"lang": lang}
        panel.pattern, panel.pattern_since = "grey", now
        with open(os.path.join(out, f"pattern_grey_{lang}.png"), "wb") as f:
            f.write(panel.pattern_canvas(now).png())
        panel.pattern = "ghost"
        with open(os.path.join(out, f"pattern_ghost_{lang}.png"), "wb") as f:
            f.write(panel.pattern_canvas(now).png())
        panel.pattern = "ghost_check"
        with open(os.path.join(out, f"pattern_ghost_check_{lang}.png"), "wb") as f:
            f.write(panel.pattern_canvas(now).png())
    if panel.cut:
        print("shortened texts:", *sorted(set(panel.cut)), sep="\n  ")
    print("previews written to", out)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
    elif len(sys.argv) == 1:
        run()
    else:
        print(__doc__)
        sys.exit(2)
