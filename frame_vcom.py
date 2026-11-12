#!/usr/bin/env python3
# Copyright (c) 2026 ClericC - MIT License - https://github.com/ClericC/frame-column-correction
"""Column Correction (Frame VCOM) - a SteamVR dashboard panel for the vcom-fix column-correction service on the Steam Frame.

The panel never touches the displays itself: it only edits /home/steamos/vcom-fix/vcom.conf.
The root service vcom-fix reads that file, applies the VCOM values and reports back in /run/vcom-fix.state.

Usage:
  frame_vcom.py                 run as a SteamVR dashboard overlay
  frame_vcom.py --preview DIR   render sample screens as PNG files (no SteamVR needed)
"""
import ctypes
import json
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
MIN_GAP = 3          # degrees between the cold and the hot calibration point
STALE_S = 10         # service state older than this counts as "not running"
CONFIRM_S = 4        # seconds a "press again to confirm" stays armed
TEMP_REDRAW_S = 30   # temperatures alone redraw the panel at most this often (every upload blinks)

# ------------------------------------------------------------------ texts

TEXT = {
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
        "confirm": "Ещё раз — подтвердить",
        "close": "Закрыть",
        "stale": "Служба vcom-fix не отвечает",
        "no_factory": "Не удалось прочитать заводские значения дисплеев",
        "disabled_note": "Выключено: заводские значения",
        "m_saved_cold": "Холодная точка сохранена: {t} °C → {l} / {r}",
        "m_saved_hot": "Горячая точка сохранена: {t} °C → {l} / {r}",
        "m_too_warm": "Слишком тепло для холодной точки (нужно ≤ {t} °C)",
        "m_too_cold": "Слишком холодно для горячей точки (нужно ≥ {t} °C)",
        "m_need_on": "Сначала включите коррекцию",
        "m_no_data": "Нет данных от службы vcom-fix",
        "m_write_err": "Не удалось сохранить настройки: {e}",
        "m_trim_limit": "Предел поправки: ±{m}",
    },
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
        "confirm": "Press again to confirm",
        "close": "Close",
        "stale": "Service vcom-fix is not responding",
        "no_factory": "Cannot read the displays' factory values",
        "disabled_note": "Off: factory values",
        "m_saved_cold": "Cold point saved: {t} °C → {l} / {r}",
        "m_saved_hot": "Hot point saved: {t} °C → {l} / {r}",
        "m_too_warm": "Too warm for the cold point (needs ≤ {t} °C)",
        "m_too_cold": "Too cold for the hot point (needs ≥ {t} °C)",
        "m_need_on": "Turn the correction on first",
        "m_no_data": "No data from the vcom-fix service",
        "m_write_err": "Could not save the settings: {e}",
        "m_trim_limit": "Trim limit: ±{m}",
    },
}
LANGS = ("ru", "en")

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


def save_point(kind, conf, state):
    """Store the currently applied offsets at the current display temperature as the cold or hot point.
    The trims are folded into the point and reset, so the output does not jump. Returns (changes, msg)."""
    if not state_fresh(state) or state.get("error") or not isinstance(state.get("display_est_mc"), int):
        return {}, ("m_no_data", {})
    if state.get("enabled") != 1:
        return {}, ("m_need_on", {})
    t = int(round(state["display_est_mc"] / 1000))
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
BTN_HOVER = (70, 80, 95)
ACCENT = (79, 163, 255)
ACCENT_DARK = (10, 30, 55)


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
    def __init__(self, glyphs):
        self.g = glyphs
        self.px = bytearray(W * H * 4)

    def fill(self, x0, y0, x1, y1, col):
        x0, x1 = max(0, x0), min(W, x1)
        y0, y1 = max(0, y0), min(H, y1)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes((col[0], col[1], col[2], 255)) * (x1 - x0)
        for y in range(y0, y1):
            o = (y * W + x0) * 4
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
                if 0 <= y < H and 0 <= gx and gx + w <= W:
                    o = (y * W + gx) * 4
                    self.px[o:o + len(row)] = row
            x += g.get(str(ord(ch)), g["63"])[4]

    def text_mid(self, s, x0, y0, x1, y1, font, fg, bg):
        """Text centred in a box (vertically by the cap height)."""
        m = self.g.meta[font]
        cap = m["ascent"] * 0.72
        self.text(s, (x0 + x1) // 2, int((y0 + y1) / 2 + cap / 2), font, fg, bg, "center")

    def png(self):
        raw = b"".join(b"\x00" + bytes(self.px[y * W * 4:(y + 1) * W * 4]) for y in range(H))
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------ the panel


class Panel:
    def __init__(self, glyphs):
        self.c = Canvas(glyphs)
        self.settings = load_settings()
        self.conf, self.state = {}, {}
        self.buttons = []           # (x0, y0, x1, y1, id)
        self.hover = None
        self.armed = None           # (button id, until) for two-step buttons
        self.msg = None             # (key, args, colour, until)
        self.quit = False

    @property
    def t(self):
        return TEXT[self.settings["lang"]]

    def _major(self):
        st = self.state
        return (self.conf, st.get("left"), st.get("right"), st.get("curve_left"), st.get("curve_right"),
                st.get("trim_left"), st.get("trim_right"), st.get("enabled"), state_fresh(st))

    def refresh(self):
        """Re-read the files. Returns (major, minor): major = values/settings changed (redraw now),
        minor = only the temperatures changed (redraw rarely: every upload makes the panel blink)."""
        old_major, old_temps = self._major(), (self.state.get("display_est_mc"), self.state.get("camera_mc"))
        self.conf, self.state = read_kv(CONF), read_kv(STATE)
        temps = (self.state.get("display_est_mc"), self.state.get("camera_mc"))
        return self._major() != old_major, temps != old_temps

    def tick(self, now):
        """Expire timed UI elements; True if a redraw is needed."""
        changed = False
        if self.armed and now > self.armed[1]:
            self.armed, changed = None, True
        if self.msg and now > self.msg[3]:
            self.msg, changed = None, True
        return changed

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

    def click(self, bid):
        now = time.time()
        if bid in ("save_cold", "save_hot"):
            if not (self.armed and self.armed[0] == bid and now <= self.armed[1]):
                self.armed = (bid, now + CONFIRM_S)
                return
            self.armed = None
            changes, msg = save_point("cold" if bid == "save_cold" else "hot", self.conf, read_kv(STATE))
            if self.apply(changes):
                self.say(msg, ok=bool(changes))
        elif bid == "toggle":
            self.apply({"ENABLED": 0 if self.conf.get("ENABLED", 0) == 1 else 1})
        elif bid.startswith("trim_"):
            _, side, op = bid.split("_")
            changes, msg = trim_change(self.conf, side, {"minus": -1, "plus": 1, "reset": 0}[op])
            if self.apply(changes):
                self.say(msg, ok=False)
        elif bid.startswith("lang_") and bid[5:] in TEXT:
            self.settings["lang"] = bid[5:]
            save_settings(self.settings)
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
        while text and self.c.g.width(text + "…", font) > maxw:
            text = text[:-1]
        return text.rstrip() + "…"

    def button(self, x0, y0, x1, y1, bid, label, font="m", base=BTN, fg=FG):
        col = base  # no hover highlight: every redraw makes the panel blink
        for smaller in ("m", "s"):  # shrink a label only if it does not fit
            if self.c.g.width(label, font) <= x1 - x0 - 20:
                break
            font = smaller
        self.c.fill(x0, y0, x1, y1, col)
        self.c.text_mid(label, x0, y0, x1, y1, font, fg, col)
        self.buttons.append((x0, y0, x1, y1, bid))

    def render(self):
        c, t, st, cf = self.c, self.t, self.state, self.conf
        self.buttons = []
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
        if fresh and st.get("error") == "no_factory_values":
            c.text(self.fit(t["no_factory"], "m", W - 80), W // 2, 150, "m", BAD, BG, "center")
        elif fresh:
            cam, est = st.get("camera_mc"), st.get("display_est_mc")
            fmt = lambda v: f"{v / 1000:.1f} °C" if isinstance(v, int) else "—"
            c.text(f"{t['camera']}  {fmt(cam)}", 40, 150, "m", DIM, BG)
            c.text(f"{t['display']}  {fmt(est)}", 984, 150, "m", FG, BG, "right")
        else:
            c.text(t["stale"], W // 2, 150, "m", BAD, BG, "center")

        # eye cards
        for i, side in enumerate(("left", "right")):
            x0 = 40 + i * 487
            x1 = x0 + 457
            c.fill(x0, 182, x1, 480, CARD)
            c.text(t[side], x0 + 28, 226, "mb", FG, CARD)
            if applied and enabled:
                val, curve = st.get(side, 0), st.get("curve_" + side, 0)
                trim = st.get("trim_" + side, 0)
                c.text(sgn(val), (x0 + x1) // 2, 340, "xl", FG, CARD, "center")
                c.text(t["detail"].format(curve=sgn(curve), trim=sgn(trim)), (x0 + x1) // 2, 386, "s", DIM, CARD, "center")
            elif applied:
                c.text("0", (x0 + x1) // 2, 340, "xl", DIM, CARD, "center")
                c.text(t["disabled_note"], (x0 + x1) // 2, 386, "s", DIM, CARD, "center")
            else:
                c.text("—", (x0 + x1) // 2, 340, "xl", DIM, CARD, "center")
            by0, by1 = 408, 462
            self.button(x0 + 24, by0, x0 + 134, by1, f"trim_{side}_minus", "−", "l")
            self.button(x0 + 150, by0, x1 - 150, by1, f"trim_{side}_reset", t["reset"], "m")
            self.button(x1 - 134, by0, x1 - 24, by1, f"trim_{side}_plus", "+", "l")

        # calibration (a message, if any, temporarily takes the place of the caption: full width there)
        if self.msg:
            key, args, col, _ = self.msg
            c.text(self.fit(t[key].format(**args), "s", W - 80), 40, 530, "s", col, BG)
        else:
            c.text(t["calib"], 40, 530, "s", DIM, BG)
        # one font size for both buttons, so they look the same
        cal_font = "m" if all(c.g.width(t[k], "m") <= 457 - 20 for k in ("save_cold", "save_hot")) else "s"
        for i, (bid, kind) in enumerate((("save_cold", "COLD"), ("save_hot", "HOT"))):
            x0 = 40 + i * 487
            x1 = x0 + 457
            armed = self.armed and self.armed[0] == bid
            label = t["confirm"] if armed else t["save_" + bid[5:]]
            self.button(x0, 548, x1, 612, bid, label, cal_font,
                        base=WARN if armed else BTN, fg=ACCENT_DARK if armed else FG)
            info = t["point"].format(t=cf.get(kind + "_TEMP", "?"), l=sgn(cf.get(kind + "_LEFT", 0)),
                                     r=sgn(cf.get(kind + "_RIGHT", 0)))
            c.text(info, (x0 + x1) // 2, 646, "s", DIM, BG, "center")

        # footer: close, language
        c.fill(0, 682, W, H, HEAD)
        self.button(24, 700, 184, 750, "close", t["close"], "s")
        lang = self.settings["lang"]
        for j, code in enumerate(LANGS):
            x0 = 820 + j * 86
            sel = code == lang
            self.button(x0, 700, x0 + 80, 750, "lang_" + code, code.upper(), "mb" if sel else "m",
                        base=ACCENT if sel else BTN, fg=ACCENT_DARK if sel else FG)
        return c.px


# ------------------------------------------------------------------ OpenVR (C API through ctypes)

# Indices into the C function tables of OpenVR SDK v2.15.6 (IVROverlay_028 / IVRSystem_026),
# taken from openvr_capi.h with offsetof() for aarch64.
OV = {"CreateOverlay": 1, "DestroyOverlay": 3, "SetOverlayFlag": 11, "SetOverlayWidthInMeters": 22,
      "SetOverlayTransformTrackedDeviceRelative": 35, "ShowOverlay": 43, "PollNextOverlayEvent": 48,
      "SetOverlayInputMethod": 50, "SetOverlayMouseScale": 52, "SetOverlayRaw": 62, "SetOverlayFromFile": 63,
      "CreateDashboardOverlay": 67, "ShowDashboard": 72}
OV_LEN, SYS_LEN = 82, 51
SYS_POLL, SYS_ACK_QUIT = 30, 47
EV_SIZE, EV_DATA = 60, 12
EV_MOUSE_MOVE, EV_MOUSE_DOWN, EV_MOUSE_UP, EV_FOCUS_LEAVE, EV_QUIT = 300, 301, 302, 304, 700
APP_OVERLAY, INPUT_MOUSE, FLAG_CLICK_STABILIZATION = 2, 1, 134217728
KEY = b"frame.vcom"
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
        P64 = ctypes.POINTER(U64)
        self.CreateDashboardOverlay = f(OV["CreateDashboardOverlay"], I32, ctypes.c_char_p, ctypes.c_char_p, P64, P64)
        self.CreateOverlay = f(OV["CreateOverlay"], I32, ctypes.c_char_p, ctypes.c_char_p, P64)
        self.DestroyOverlay = f(OV["DestroyOverlay"], I32, U64)
        self.SetOverlayFlag = f(OV["SetOverlayFlag"], I32, U64, I32, ctypes.c_bool)
        self.SetOverlayWidthInMeters = f(OV["SetOverlayWidthInMeters"], I32, U64, ctypes.c_float)
        self.SetOverlayTransformTrackedDeviceRelative = f(OV["SetOverlayTransformTrackedDeviceRelative"], I32,
                                                          U64, U32, ctypes.c_void_p)
        self.ShowOverlay = f(OV["ShowOverlay"], I32, U64)
        self.PollNextOverlayEvent = f(OV["PollNextOverlayEvent"], ctypes.c_bool, U64, ctypes.c_void_p, U32)
        self.SetOverlayInputMethod = f(OV["SetOverlayInputMethod"], I32, U64, I32)
        self.SetOverlayMouseScale = f(OV["SetOverlayMouseScale"], I32, U64, ctypes.POINTER(Vec2))
        self.SetOverlayRaw = f(OV["SetOverlayRaw"], I32, U64, ctypes.c_void_p, U32, U32, U32)
        self.SetOverlayFromFile = f(OV["SetOverlayFromFile"], I32, U64, ctypes.c_char_p)
        self.ShowDashboard = f(OV["ShowDashboard"], None, ctypes.c_char_p)
        self.PollNextEvent = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, U32)(self.sys[SYS_POLL])
        self.AcknowledgeQuit = ctypes.CFUNCTYPE(None)(self.sys[SYS_ACK_QUIT])
        for name in ("CreateDashboardOverlay", "SetOverlayRaw", "PollNextOverlayEvent", "SetOverlayInputMethod",
                     "SetOverlayMouseScale", "DestroyOverlay"):
            if getattr(self, name) is None:
                raise SystemExit(f"OpenVR function {name} is not available")
        self.handle = U64(0)
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
            self.SetOverlayTransformTrackedDeviceRelative(self.handle, 0, ctypes.cast(m, ctypes.c_void_p))
            self.SetOverlayWidthInMeters(self.handle, 1.0)
            self.ShowOverlay(self.handle)
        self.SetOverlayInputMethod(self.handle, INPUT_MOUSE)
        scale = Vec2(W, H)
        self.SetOverlayMouseScale(self.handle, ctypes.byref(scale))
        if self.SetOverlayFlag:
            self.SetOverlayFlag(self.handle, FLAG_CLICK_STABILIZATION, True)

    def upload(self, px):
        buf = (ctypes.c_ubyte * len(px)).from_buffer(px)
        self.SetOverlayRaw(self.handle, ctypes.cast(buf, ctypes.c_void_p), W, H, 4)

    def shutdown(self):
        try:
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
    print("Column Correction panel running", flush=True)
    while not panel.quit:
        dirty = False
        while vr.PollNextEvent(ev, EV_SIZE):
            if struct.unpack_from("<I", ev.raw, 0)[0] == EV_QUIT:
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
        dirty |= panel.tick(now)
        if dirty and not panel.quit:
            vr.upload(panel.render())
            last_draw = now
        time.sleep(0.03)
    vr.shutdown()


# ------------------------------------------------------------------ preview (no SteamVR)


def preview(out):
    os.makedirs(out, exist_ok=True)
    panel = Panel(Glyphs(HERE))
    now = int(time.time())
    conf = {"COLD_TEMP": 34, "COLD_LEFT": 5, "COLD_RIGHT": 8, "HOT_TEMP": 52, "HOT_LEFT": 28, "HOT_RIGHT": 35,
            "LAG_MIN": 22, "LEFT_TRIM": 2, "RIGHT_TRIM": -1, "ENABLED": 1}
    state = {"enabled": 1, "camera_mc": 50300, "display_est_mc": 44100, "curve_left": 17, "curve_right": 22,
             "trim_left": 2, "trim_right": -1, "left": 19, "right": 21, "updated": now}
    shots = [
        ("ru_normal", "ru", conf, state, {}),
        ("en_normal", "en", conf, state, {}),
        ("ru_hover_confirm", "ru", conf, state, {"hover": "trim_right_plus", "armed": ("save_hot", now + 9)}),
        ("ru_saved", "ru", conf, state, {"msg": ("m_saved_hot", {"t": 44, "l": "+19", "r": "+21"}, GOOD, now + 9)}),
        ("ru_off", "ru", dict(conf, ENABLED=0), dict(state, enabled=0, left=0, right=0), {}),
        ("en_stale", "en", conf, dict(state, updated=now - 60), {}),
        ("ru_no_factory", "ru", conf, dict(state, error="no_factory_values"), {}),
        ("ru_new_install", "ru", {"COLD_TEMP": 34, "HOT_TEMP": 52, "ENABLED": 0},
         dict(state, enabled=0, left=0, right=0, curve_left=0, curve_right=0, trim_left=0, trim_right=0), {}),
        ("ru_long_msg", "ru", conf, state, {"msg": ("m_too_cold", {"t": 37}, WARN, now + 9)}),
    ]
    for name, lang, cf, st, extra in shots:
        panel.settings = {"lang": lang}
        panel.conf, panel.state = cf, st
        panel.hover, panel.armed, panel.msg = extra.get("hover"), extra.get("armed"), extra.get("msg")
        panel.render()
        with open(os.path.join(out, name + ".png"), "wb") as f:
            f.write(panel.c.png())
    print("previews written to", out)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
    elif len(sys.argv) == 1:
        run()
    else:
        print(__doc__)
        sys.exit(2)
