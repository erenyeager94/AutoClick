import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    import winreg
except Exception:
    winreg = None

try:
    from PIL import Image, ImageTk, ImageEnhance, ImageOps
    PIL_AVAILABLE = True
except Exception:
    Image = ImageTk = ImageEnhance = ImageOps = None
    PIL_AVAILABLE = False

import pyautogui
from pynput import keyboard


# ============================================================
# WINDOWS DPI FIX
# ============================================================
if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


APP_NAME = "AutoClick"

# ============================================================
# EXE / RESOURCE PATHS
# ============================================================
# APP_DIR is writable and remains beside the .exe after PyInstaller build.
# BUNDLE_DIR is PyInstaller's temporary resource directory (_MEIPASS).
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR


def resource_path(filename):
    """Prefer a file beside the EXE; otherwise use the bundled copy."""
    external = os.path.join(APP_DIR, filename)
    if os.path.exists(external):
        return external
    return os.path.join(BUNDLE_DIR, filename)


BASE_DIR = APP_DIR
# Saved configs are stored internally in the current Windows user's Registry.
# This keeps saved_configs.json out of the EXE folder while preserving configs
# across app restarts and EXE updates. Existing legacy JSON is auto-migrated.
LEGACY_CONFIG_FILE = os.path.join(APP_DIR, "saved_configs.json")
REGISTRY_PATH = r"Software\AutoClick"
REGISTRY_VALUE = "SavedConfigs"
FALLBACK_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".autoclick_saved_configs.json")

GIF_MAIN = resource_path("hacker.gif")
GIF_ALT = resource_path("hacker1.gif")
GIF_EXTRA = resource_path("hacker2.gif")
APP_ICON_IMAGE = resource_path("AutoClicker.jpg")

pyautogui.PAUSE = 0.02
pyautogui.FAILSAFE = True


# ============================================================
# RED GLOW + GREEN TERMINAL TEXT THEME
# ============================================================
BG_MAIN = "#000000"          # Pure black
BG_PANEL = "#020000"         # Near-black red glass
BG_CARD = "#040000"          # Transparent-look black/red card
BG_INPUT = "#080000"         # Deep red-black input
BG_HOVER = "#180000"         # Red-black hover

RED = "#ff0000"              # Pure neon red
RED_BRIGHT = "#ff1010"       # Hot red highlight
RED_LIGHT = "#d90000"        # Medium red
RED_SOFT = "#5a0000"         # Dark red glow edge
RED_GLOW = "#ff0000"         # Strong neon glow

CYAN = "#ff0000"             # Red text / accent
CYAN_BRIGHT = "#ff0000"      # White highlight text
CYAN_DARK = "#b80000"        # Dark red text
CYAN_SOFT = "#750000"        # Soft dark red

TEXT = "#ffffff"             # Main text = WHITE
TEXT_SOFT = "#ff2b2b"        # Secondary text = RED
TEXT_MUTED = "#cfcfcf"       # Small / muted text = soft WHITE
TEXT_RED = "#ff0000"         # Important / danger text = RED
TEXT_CYAN = "#ffffff"        # Normal visible text = WHITE       # Kept for compatibility: visible text is green

BORDER = "#c40000"           # Normal red border
BORDER_BRIGHT = "#ff0000"    # Active neon border

TRANSPARENT_KEY = "#010101"


# ============================================================
# HELPERS
# ============================================================
def geometry_at(width, height, x, y):
    return f"{int(width)}x{int(height)}+{max(0, int(x))}+{max(0, int(y))}"


def _hex_to_colorref(value):
    """Convert #RRGGBB to a Windows COLORREF integer."""
    value = (value or "#010101").lstrip("#")
    if len(value) != 6:
        value = "010101"
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return r | (g << 8) | (b << 16)


def apply_window_colorkey(win, color=TRANSPARENT_KEY, click_through=False, no_activate=False):
    """
    Make a Tk Toplevel visually transparent using a real Windows color key.
    This is more reliable than only using Tk's -transparentcolor and fixes
    the black rectangle that can appear around scope / marker windows.

    click_through=True is used only for SAVED target markers / floating HUDs.
    The target selector stays clickable so the user can lock a point.
    """
    try:
        win.configure(bg=color)
    except Exception:
        pass

    try:
        win.wm_attributes("-transparentcolor", color)
    except Exception:
        try:
            win.attributes("-transparentcolor", color)
        except Exception:
            pass

    if os.name != "nt":
        return

    try:
        win.update_idletasks()
        hwnd = win.winfo_id()

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        LWA_COLORKEY = 0x00000001

        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if click_through:
            style |= WS_EX_TRANSPARENT
        if no_activate:
            style |= WS_EX_NOACTIVATE
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        user32.SetLayeredWindowAttributes(hwnd, _hex_to_colorref(color), 0, LWA_COLORKEY)
    except Exception:
        pass


def hotkey_to_pynput(value):
    value = (value or "").strip()
    if not value:
        raise ValueError("Shortcut empty hai.")

    parts = [p.strip().lower() for p in value.split("+") if p.strip()]
    result = []

    special = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "win": "<cmd>",
        "windows": "<cmd>",
    }

    for part in parts:
        if part in special:
            result.append(special[part])
        elif part.startswith("f") and part[1:].isdigit():
            num = int(part[1:])
            if num < 1 or num > 24:
                raise ValueError("Function key F1 se F24 ke beech honi chahiye.")
            result.append(f"<f{num}>")
        elif len(part) == 1:
            result.append(part)
        else:
            raise ValueError(f"Unsupported shortcut: {part}")

    return "+".join(result)


def normalize_cycle_rule(action):
    """Ensure every action has a valid cycle window."""
    try:
        start_cycle = max(1, int(action.get("start_cycle", 1)))
    except Exception:
        start_cycle = 1

    try:
        end_cycle = max(0, int(action.get("end_cycle", 0)))
    except Exception:
        end_cycle = 0

    if end_cycle and end_cycle < start_cycle:
        end_cycle = start_cycle

    action["start_cycle"] = start_cycle
    action["end_cycle"] = end_cycle
    return action


def cycle_rule_text(action):
    normalize_cycle_rule(action)
    start_cycle = int(action.get("start_cycle", 1))
    end_cycle = int(action.get("end_cycle", 0))

    if start_cycle == 1 and end_cycle == 0:
        return "every cycle"
    if end_cycle == 0:
        return f"cycle {start_cycle}+"
    if start_cycle == end_cycle:
        return f"cycle {start_cycle} only"
    return f"cycles {start_cycle}-{end_cycle}"


def action_active_for_cycle(action, cycle_number):
    normalize_cycle_rule(action)
    start_cycle = int(action.get("start_cycle", 1))
    end_cycle = int(action.get("end_cycle", 0))

    if cycle_number < start_cycle:
        return False
    if end_cycle > 0 and cycle_number > end_cycle:
        return False
    return True


def action_text(action):
    kind = action.get("type")
    rule = cycle_rule_text(action)

    if kind == "click":
        return (
            f"{action.get('button', 'left').title()} click x{int(action.get('clicks', 1))} "
            f"at X={action['x']} Y={action['y']} "
            f"• delay {float(action.get('delay', 0.5)):g}s • {rule}"
        )

    if kind == "scroll":
        amount = int(action.get("amount", -5))
        direction = "UP" if amount > 0 else "DOWN"
        return (
            f"Scroll {direction} x{abs(amount)} at X={action['x']} Y={action['y']} "
            f"• delay {float(action.get('delay', 0.5)):g}s • {rule}"
        )

    if kind == "swipe":
        return (
            f"Swipe ({action['x1']},{action['y1']}) → ({action['x2']},{action['y2']}) "
            f"• {float(action.get('duration', 0.5)):g}s "
            f"• delay {float(action.get('delay', 0.5)):g}s • {rule}"
        )

    return "Unknown action"


# ============================================================
# ANIMATED GIF BACKGROUND / BANNER
# ============================================================
class AnimatedGifSurface:
    """
    Lightweight GIF player for Tkinter using Pillow.
    It does NOT change any automation workflow; it is UI-only.
    """
    def __init__(
        self,
        parent,
        path,
        width,
        height,
        brightness=0.42,
        place=True,
        bg=BG_MAIN,
        fallback_text=""
    ):
        self.parent = parent
        self.path = path
        self.width = int(width)
        self.height = int(height)
        self.brightness = float(brightness)
        self.index = 0
        self.after_id = None
        self.photo = None
        self.image = None
        self.frame_count = 0
        self.running = False

        self.label = tk.Label(
            parent,
            bg=bg,
            bd=0,
            highlightthickness=0,
            text=fallback_text,
            fg=TEXT_MUTED,
            font=("Georgia", 9)
        )

        if place:
            self.label.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            self.label.pack(fill="both", expand=True)

        if PIL_AVAILABLE and path and os.path.exists(path):
            try:
                self.image = Image.open(path)
                self.frame_count = max(1, int(getattr(self.image, "n_frames", 1)))
                self.running = True
                self._next_frame()
            except Exception as exc:
                self.label.config(text="")
        else:
            if not PIL_AVAILABLE:
                self.label.config(text="")
            elif path and not os.path.exists(path):
                self.label.config(text="")

    def _next_frame(self):
        if not self.running or self.image is None:
            return

        try:
            self.image.seek(self.index)
            frame = self.image.convert("RGB")
            frame = frame.resize((self.width, self.height), Image.Resampling.BILINEAR)
            frame = ImageEnhance.Brightness(frame).enhance(self.brightness)

            self.photo = ImageTk.PhotoImage(frame)
            self.label.config(image=self.photo, text="")

            duration = int(self.image.info.get("duration", 80) or 80)
            duration = max(35, min(duration, 180))

            self.index = (self.index + 1) % self.frame_count
            self.after_id = self.parent.after(duration, self._next_frame)
        except (tk.TclError, RuntimeError):
            self.running = False
        except Exception:
            self.index = (self.index + 1) % max(1, self.frame_count)
            try:
                self.after_id = self.parent.after(90, self._next_frame)
            except Exception:
                self.running = False

    def stop(self):
        self.running = False
        if self.after_id:
            try:
                self.parent.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None


def first_existing_gif(*paths):
    for path in paths:
        if path and os.path.exists(path):
            return path
    return paths[0] if paths else ""


# ============================================================
# CANVAS GIF PLAYER (TRANSPARENT DASHBOARD BACKGROUND)
# ============================================================
class CanvasGifPlayer:
    """Animate a GIF inside a Tk Canvas item.

    Because the dashboard UI is also drawn on the same Canvas, the neon
    panels can use stipple fills and the GIF remains visible behind them,
    which gives a much closer "transparent glass" look than normal Frames.
    """
    def __init__(self, canvas, path, x, y, width, height, brightness=0.30, crop=True, min_delay=85):
        self.canvas = canvas
        self.path = path
        self.x = int(x)
        self.y = int(y)
        self.width = int(width)
        self.height = int(height)
        self.brightness = float(brightness)
        self.crop = bool(crop)
        self.min_delay = int(min_delay)
        self.index = 0
        self.image = None
        self.photo = None
        self.after_id = None
        self.running = False
        self.item_id = self.canvas.create_image(self.x, self.y, anchor="nw")
        self.canvas.tag_lower(self.item_id)

        if PIL_AVAILABLE and path and os.path.exists(path):
            try:
                self.image = Image.open(path)
                self.frame_count = max(1, int(getattr(self.image, "n_frames", 1)))
                self.running = True
                self._next()
            except Exception:
                self.running = False
        else:
            self.frame_count = 0

    def _render(self, frame):
        frame = frame.convert("RGB")
        if self.crop and ImageOps is not None:
            frame = ImageOps.fit(frame, (self.width, self.height), method=Image.Resampling.BILINEAR)
        else:
            frame = frame.resize((self.width, self.height), Image.Resampling.BILINEAR)
        frame = ImageEnhance.Brightness(frame).enhance(self.brightness)
        return frame

    def _next(self):
        if not self.running or self.image is None:
            return
        try:
            self.image.seek(self.index)
            frame = self._render(self.image.copy())
            self.photo = ImageTk.PhotoImage(frame)
            self.canvas.itemconfig(self.item_id, image=self.photo)
            self.canvas.tag_lower(self.item_id)
            duration = int(self.image.info.get("duration", 90) or 90)
            duration = max(self.min_delay, min(duration, 180))
            self.index = (self.index + 1) % max(1, self.frame_count)
            self.after_id = self.canvas.after(duration, self._next)
        except (tk.TclError, RuntimeError):
            self.running = False
        except Exception:
            self.index = (self.index + 1) % max(1, self.frame_count)
            try:
                self.after_id = self.canvas.after(max(100, self.min_delay), self._next)
            except Exception:
                self.running = False

    def stop(self):
        self.running = False
        if self.after_id:
            try:
                self.canvas.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None


# ============================================================
# TARGET MARKER / SCOPE
# ============================================================
class TargetMarker:
    """
    Compact gun-scope style marker shown after a target is saved.

    Important:
      - NO black card / square background.
      - Bright red precision dot stays exactly on the click coordinate.
      - Window is click-through, so it never blocks the real click.
      - Small sequence / cycle information remains visible without covering UI.
    """
    def __init__(self, root, action, number):
        self.action = normalize_cycle_rule(dict(action))
        self.number = number
        self.kind = self.action.get("type", "click")

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANSPARENT_KEY)

        if self.kind == "swipe":
            x = int(self.action["x1"])
            y = int(self.action["y1"])
        else:
            x = int(self.action["x"])
            y = int(self.action["y"])

        # Compact scope: point itself is always the exact center.
        self.size = 92
        self.cx = self.size // 2
        self.cy = self.size // 2
        self.win.geometry(geometry_at(self.size, self.size, x - self.cx, y - self.cy))

        self.canvas = tk.Canvas(
            self.win,
            width=self.size,
            height=self.size,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        apply_window_colorkey(self.win, TRANSPARENT_KEY, click_through=True, no_activate=True)

        c = self.canvas
        s = self.size
        cx, cy = self.cx, self.cy

        # Soft fake glow layers. They are outlines only; center stays transparent.
        c.create_oval(7, 7, s-7, s-7, outline="#240000", width=7)
        c.create_oval(11, 11, s-11, s-11, outline="#5b0000", width=4)
        self.scope_ring = c.create_oval(15, 15, s-15, s-15, outline="#ff0000", width=2)
        self.inner_ring = c.create_oval(24, 24, s-24, s-24, outline="#9c0000", width=1)

        # Broken / tactical scope arcs.
        self.pulse_items = [self.scope_ring, self.inner_ring]
        for ang in (8, 68, 128, 188, 248, 308):
            arc = c.create_arc(
                10, 10, s-10, s-10,
                start=ang, extent=27,
                style="arc", outline="#ff2020", width=3,
            )
            self.pulse_items.append(arc)

        # Precision crosshair. Gap at the exact target keeps the red dot clean.
        arm_out, arm_in = 2, 29
        for x1, y1, x2, y2 in (
            (cx, arm_out, cx, arm_in),
            (cx, s-arm_in, cx, s-arm_out),
            (arm_out, cy, arm_in, cy),
            (s-arm_in, cy, s-arm_out, cy),
        ):
            c.create_line(x1, y1, x2, y2, fill="#e00000", width=2)

        c.create_line(cx-16, cy, cx-6, cy, fill="#ff4040", width=1)
        c.create_line(cx+6, cy, cx+16, cy, fill="#ff4040", width=1)
        c.create_line(cx, cy-16, cx, cy-6, fill="#ff4040", width=1)
        c.create_line(cx, cy+6, cx, cy+16, fill="#ff4040", width=1)

        # Gun-sight centre: bright hot red dot + tiny white-hot core.
        self.dot_glow = c.create_oval(cx-7, cy-7, cx+7, cy+7, outline="#5e0000", width=4)
        self.dot_ring = c.create_oval(cx-4, cy-4, cx+4, cy+4, outline="#ff0000", width=2)
        self.dot = c.create_oval(cx-2, cy-2, cx+2, cy+2, fill="#ff1a1a", outline="")
        self.core = c.create_oval(cx-1, cy-1, cx+1, cy+1, fill="#fff0f0", outline="")
        self.pulse_items.extend([self.dot_glow, self.dot_ring])

        # Small sequence badge; does not cover the target point.
        kind_letter = {"click": "C", "scroll": "R", "swipe": "S"}.get(self.kind, "N")
        c.create_text(
            cx, 12,
            text=f"{kind_letter}{number}",
            fill="#ff3a3a",
            font=("Georgia", 7, "bold"),
        )

        start_cycle = int(self.action.get("start_cycle", 1))
        end_cycle = int(self.action.get("end_cycle", 0))
        rule = f"{start_cycle}→∞" if end_cycle == 0 else f"{start_cycle}→{end_cycle}"
        c.create_text(
            cx, s-11,
            text=rule,
            fill="#b80000",
            font=("Georgia", 7, "bold"),
        )

        # Small cardinal locator diamonds.
        for dx, dy in ((0, -32), (32, 0), (0, 32), (-32, 0)):
            x0, y0 = cx+dx, cy+dy
            c.create_polygon(
                x0, y0-2, x0+2, y0, x0, y0+2, x0-2, y0,
                fill="#ff0000", outline="",
            )

        self._pulse_on = False
        self.after_id = None
        self._pulse()

    def _pulse(self):
        try:
            self._pulse_on = not self._pulse_on
            hot = "#ff3838" if self._pulse_on else "#a60000"
            for item in self.pulse_items:
                self.canvas.itemconfig(item, outline=hot)
            self.canvas.itemconfig(self.dot, fill="#ff4040" if self._pulse_on else "#ff0000")
            self.after_id = self.win.after(320, self._pulse)
        except Exception:
            self.after_id = None

    def destroy(self):
        try:
            if self.after_id:
                self.win.after_cancel(self.after_id)
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


class TargetSelector:
    """
    Low-latency transparent target picker.

    Performance / accuracy changes:
      - Reticle items are moved as ONE canvas tag instead of redrawing every shape.
      - Windows GetCursorPos is polled at ~8 ms as a fallback between Tk motion events.
      - LEFT CLICK uses event.x_root / event.y_root, so the saved coordinate is the
        exact click position even if a frame is rendered a few milliseconds later.
      - No black overlay/card; only red scope graphics are visible.
    """
    def __init__(self, app, mode, callback):
        self.app = app
        self.mode = mode
        self.callback = callback
        self.first_point = None
        self.finished = False
        self.last_x = None
        self.last_y = None
        self.poll_id = None
        self.pulse_id = None
        self._pulse_on = False

        sw = app.root.winfo_screenwidth()
        sh = app.root.winfo_screenheight()
        self.sw = int(sw)
        self.sh = int(sh)

        self.overlay = tk.Toplevel(app.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.configure(bg=TRANSPARENT_KEY, cursor="crosshair")
        self.overlay.geometry(f"{self.sw}x{self.sh}+0+0")

        self.canvas = tk.Canvas(
            self.overlay,
            width=self.sw,
            height=self.sh,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)

        # Visual transparency only. The overlay must still receive mouse clicks.
        apply_window_colorkey(
            self.overlay,
            TRANSPARENT_KEY,
            click_through=False,
            no_activate=False,
        )

        c = self.canvas

        # ------------------------------------------------------------
        # FULL-SCREEN LASER GUIDES
        # ------------------------------------------------------------
        self.vline_glow = c.create_line(0, 0, 0, self.sh, fill="#350000", width=3)
        self.hline_glow = c.create_line(0, 0, self.sw, 0, fill="#350000", width=3)
        self.vline = c.create_line(0, 0, 0, self.sh, fill="#ff0000", width=1)
        self.hline = c.create_line(0, 0, self.sw, 0, fill="#ff0000", width=1)

        # ------------------------------------------------------------
        # MOVING SCOPE
        # Everything below uses the same tag. Moving the entire scope is one
        # Tcl/Tk command, which is much faster than updating every item.
        # ------------------------------------------------------------
        R = "scope_reticle"

        c.create_oval(-52, -52, 52, 52, outline="#120000", width=10, tags=(R, "pulse_dim"))
        c.create_oval(-47, -47, 47, 47, outline="#390000", width=7, tags=(R, "pulse_dim"))
        c.create_oval(-42, -42, 42, 42, outline="#8b0000", width=4, tags=(R, "pulse_mid"))
        self.scope_outer = c.create_oval(
            -37, -37, 37, 37,
            outline="#ff0000", width=2,
            tags=(R, "pulse_hot"),
        )
        self.scope_inner = c.create_oval(
            -22, -22, 22, 22,
            outline="#bb0000", width=1,
            tags=(R, "pulse_mid"),
        )

        # Broken tactical arcs.
        self.arc_items = []
        for ang in (0, 60, 120, 180, 240, 300):
            item = c.create_arc(
                -45, -45, 45, 45,
                start=ang + 8,
                extent=28,
                style="arc",
                outline="#ff2020",
                width=3,
                tags=(R, "pulse_hot"),
            )
            self.arc_items.append(item)

        # Diamond lock plate.
        self.diamond = c.create_polygon(
            0, -31,
            31, 0,
            0, 31,
            -31, 0,
            fill="",
            outline="#850000",
            width=1,
            tags=(R, "pulse_mid"),
        )

        # Precision bars around the center.
        for coords in (
            (-27, 0, -8, 0),
            (8, 0, 27, 0),
            (0, -27, 0, -8),
            (0, 8, 0, 27),
        ):
            c.create_line(*coords, fill="#ff4040", width=2, tags=(R,))

        # Micro ticks: gun-scope style.
        for px, py, x2, y2 in (
            (-15, -3, -15, 3), (15, -3, 15, 3),
            (-3, -15, 3, -15), (-3, 15, 3, 15),
        ):
            c.create_line(px, py, x2, y2, fill="#8f0000", width=1, tags=(R,))

        # Hot red precision point.
        self.dot_glow = c.create_oval(
            -9, -9, 9, 9,
            outline="#5b0000", width=5,
            tags=(R, "pulse_dim"),
        )
        self.dot_ring = c.create_oval(
            -5, -5, 5, 5,
            outline="#ff0000", width=2,
            tags=(R, "pulse_hot"),
        )
        self.dot = c.create_oval(
            -2, -2, 2, 2,
            fill="#ff1010", outline="",
            tags=(R,),
        )
        self.core = c.create_oval(
            -1, -1, 1, 1,
            fill="#ffffff", outline="",
            tags=(R,),
        )

        # Cardinal diamonds.
        for dx, dy in ((0, -34), (34, 0), (0, 34), (-34, 0)):
            c.create_polygon(
                dx, dy - 3,
                dx + 3, dy,
                dx, dy + 3,
                dx - 3, dy,
                fill="#ff0000",
                outline="",
                tags=(R,),
            )

        # Scope live-state labels.
        self.scope_state = c.create_text(
            0, -59,
            text="TARGET",
            fill="#a80000",
            font=("Georgia", 7, "bold"),
            tags=(R,),
        )

        # ------------------------------------------------------------
        # FLOATING COORDINATE TAG
        # ------------------------------------------------------------
        self.coord_box = c.create_rectangle(
            0, 0, 0, 0,
            fill=TRANSPARENT_KEY,
            outline="#8d0000",
            width=1,
        )
        self.coord_text = c.create_text(
            0, 0,
            text="X:0  Y:0",
            anchor="w",
            fill="#ff3030",
            font=("Georgia", 8, "bold"),
        )

        # ------------------------------------------------------------
        # FIXED TOP HUD
        # ------------------------------------------------------------
        hud_x1, hud_y1, hud_x2, hud_y2 = 24, 22, 650, 92
        for pad, col, wid in (
            (0, "#240000", 5),
            (3, "#720000", 3),
            (6, "#ff0000", 1),
        ):
            c.create_rectangle(
                hud_x1 + pad,
                hud_y1 + pad,
                hud_x2 - pad,
                hud_y2 - pad,
                outline=col,
                width=wid,
            )

        # HUD corner brackets.
        bracket = 18
        for coords in (
            (hud_x1+7, hud_y1+7, hud_x1+7+bracket, hud_y1+7),
            (hud_x1+7, hud_y1+7, hud_x1+7, hud_y1+7+bracket),
            (hud_x2-7-bracket, hud_y1+7, hud_x2-7, hud_y1+7),
            (hud_x2-7, hud_y1+7, hud_x2-7, hud_y1+7+bracket),
        ):
            c.create_line(*coords, fill="#ff3030", width=2)

        c.create_line(
            hud_x1 + 20, hud_y1 + 33,
            hud_x2 - 20, hud_y1 + 33,
            fill="#6b0000", width=1,
        )
        c.create_text(
            hud_x1 + 20,
            hud_y1 + 20,
            text="// RED SCOPE  //  LOW LATENCY TARGET LOCK",
            anchor="w",
            fill="#ff2020",
            font=("Georgia", 9, "bold"),
        )
        self.info_text = c.create_text(
            hud_x1 + 20,
            hud_y1 + 49,
            text="",
            anchor="w",
            fill="#ff5050",
            font=("Georgia", 9, "bold"),
        )
        self.hud_coord = c.create_text(
            hud_x2 - 20,
            hud_y1 + 49,
            text="X: 0   Y: 0",
            anchor="e",
            fill="#ff0000",
            font=("Georgia", 9, "bold"),
        )
        c.create_text(
            hud_x2 - 20,
            hud_y1 + 18,
            text="ESC  CANCEL",
            anchor="e",
            fill="#940000",
            font=("Georgia", 7, "bold"),
        )

        if mode == "point":
            c.itemconfig(
                self.info_text,
                text="MOVE SCOPE  →  LEFT CLICK TO LOCK EXACT POINT",
            )
        else:
            c.itemconfig(
                self.info_text,
                text="SWIPE  →  LOCK START POINT, THEN LOCK END POINT",
            )

        # Input bindings. Motion is the primary path; high-frequency polling
        # catches movement between Tk events for a tighter feel.
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Escape>", self.cancel)
        self.overlay.bind("<Escape>", self.cancel)
        self.canvas.focus_force()

        # Put scope at the real cursor position BEFORE the user starts moving.
        x0, y0 = self._get_cursor_pos()
        self._sync_scope(x0, y0, force=True)
        self.overlay.update_idletasks()

        self._pulse()
        self.poll_id = self.overlay.after(1, self._poll_cursor)

    # -----------------------------------------------------------------
    # FAST CURSOR / RETICLE SYNC
    # -----------------------------------------------------------------
    def _get_cursor_pos(self):
        """Fast native cursor read on Windows; pyautogui fallback elsewhere."""
        if os.name == "nt":
            try:
                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                pt = POINT()
                if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                    return int(pt.x), int(pt.y)
            except Exception:
                pass

        try:
            x, y = pyautogui.position()
            return int(x), int(y)
        except Exception:
            return 0, 0

    def _poll_cursor(self):
        if self.finished:
            return

        try:
            x, y = self._get_cursor_pos()
            self._sync_scope(x, y)
        except Exception:
            pass

        try:
            # 8 ms target (~125 Hz). Windows/Tk may coalesce timers, but it is
            # still much more responsive than relying on expensive redraws.
            self.poll_id = self.overlay.after(8, self._poll_cursor)
        except Exception:
            self.poll_id = None

    def _sync_scope(self, x, y, force=False):
        x = max(0, min(self.sw - 1, int(x)))
        y = max(0, min(self.sh - 1, int(y)))

        if not force and x == self.last_x and y == self.last_y:
            return

        if self.last_x is None or self.last_y is None:
            dx = x
            dy = y
        else:
            dx = x - self.last_x
            dy = y - self.last_y

        # ONE MOVE CALL for the whole reticle = significantly less lag.
        if dx or dy:
            self.canvas.move("scope_reticle", dx, dy)

        self.last_x = x
        self.last_y = y

        # Two guide updates only.
        self.canvas.coords(self.vline_glow, x, 0, x, self.sh)
        self.canvas.coords(self.hline_glow, 0, y, self.sw, y)
        self.canvas.coords(self.vline, x, 0, x, self.sh)
        self.canvas.coords(self.hline, 0, y, self.sw, y)

        # Coordinate tag follows scope but flips near screen edges.
        tx = x + 56
        ty = y + 40
        if tx + 122 > self.sw:
            tx = x - 156
        if ty + 24 > self.sh:
            ty = y - 58
        if tx < 8:
            tx = 8
        if ty < 12:
            ty = 12

        self.canvas.coords(self.coord_box, tx - 8, ty - 12, tx + 116, ty + 12)
        self.canvas.coords(self.coord_text, tx, ty)

        txt = f"X:{x}  Y:{y}"
        self.canvas.itemconfig(self.coord_text, text=txt)
        self.canvas.itemconfig(self.hud_coord, text=f"X: {x}   Y: {y}")

    def on_motion(self, event):
        # x_root/y_root correspond to the actual OS pointer location at this
        # exact motion event, avoiding a second pyautogui read and its delay.
        self._sync_scope(int(event.x_root), int(event.y_root))

    def on_click(self, event):
        # CRITICAL ACCURACY FIX:
        # Capture the exact click-event coordinate, not the position a few ms
        # later after another cursor read.
        x = int(event.x_root)
        y = int(event.y_root)
        self._sync_scope(x, y, force=True)

        if self.mode == "point":
            self.finish({"x": x, "y": y})
            return

        if self.first_point is None:
            self.first_point = (x, y)

            # Permanent start-lock cue while selecting swipe end.
            tag = "locked_start"
            self.canvas.delete(tag)
            self.canvas.create_oval(
                x - 15, y - 15, x + 15, y + 15,
                outline="#ff0000", width=2,
                tags=(tag,),
            )
            self.canvas.create_line(
                x - 22, y, x - 7, y,
                fill="#ff3030", width=1, tags=(tag,),
            )
            self.canvas.create_line(
                x + 7, y, x + 22, y,
                fill="#ff3030", width=1, tags=(tag,),
            )
            self.canvas.create_line(
                x, y - 22, x, y - 7,
                fill="#ff3030", width=1, tags=(tag,),
            )
            self.canvas.create_line(
                x, y + 7, x, y + 22,
                fill="#ff3030", width=1, tags=(tag,),
            )
            self.canvas.create_oval(
                x - 2, y - 2, x + 2, y + 2,
                fill="#ff0000", outline="", tags=(tag,),
            )
            self.canvas.itemconfig(
                self.info_text,
                text=f"START LOCKED  [{x}, {y}]  →  NOW LOCK END POINT",
            )
        else:
            self.finish({
                "x1": self.first_point[0],
                "y1": self.first_point[1],
                "x2": x,
                "y2": y,
            })

    def _pulse(self):
        if self.finished:
            return

        try:
            self._pulse_on = not self._pulse_on
            if self._pulse_on:
                hot = "#ff4040"
                mid = "#c00000"
                dim = "#5a0000"
                dot = "#ff5555"
            else:
                hot = "#ff0000"
                mid = "#820000"
                dim = "#280000"
                dot = "#ff0000"

            self.canvas.itemconfig("pulse_hot", outline=hot)
            self.canvas.itemconfig("pulse_mid", outline=mid)
            self.canvas.itemconfig("pulse_dim", outline=dim)
            self.canvas.itemconfig(self.dot, fill=dot)
            self.pulse_id = self.overlay.after(220, self._pulse)
        except Exception:
            self.pulse_id = None

    def cancel(self, *_):
        self.finish(None)

    def finish(self, result):
        if self.finished:
            return
        self.finished = True

        try:
            if self.poll_id:
                self.overlay.after_cancel(self.poll_id)
        except Exception:
            pass

        try:
            if self.pulse_id:
                self.overlay.after_cancel(self.pulse_id)
        except Exception:
            pass

        try:
            self.overlay.destroy()
        except Exception:
            pass

        self.callback(result)

# ACTION SETTINGS DIALOGS
# ============================================================
class ClickSettings:
    def __init__(self, parent, action, callback):
        self.callback = callback
        self.action = normalize_cycle_rule(dict(action))

        self.win = tk.Toplevel(parent)
        self.win.title("Click Settings")
        self.win.geometry("460x545")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.configure(bg=BG_MAIN)

        self.button = tk.StringVar(value=self.action.get("button", "left"))
        self.clicks = tk.IntVar(value=int(self.action.get("clicks", 1)))
        self.delay = tk.DoubleVar(value=float(self.action.get("delay", 0.5)))
        self.start_cycle = tk.IntVar(value=int(self.action.get("start_cycle", 1)))
        self.end_cycle = tk.IntVar(value=int(self.action.get("end_cycle", 0)))

        outer = tk.Frame(self.win, bg=BG_MAIN, highlightbackground=RED_GLOW, highlightthickness=1)
        outer.pack(fill="both", expand=True, padx=9, pady=9)
        body = tk.Frame(outer, bg="#020000", padx=20, pady=18)
        body.pack(fill="both", expand=True, padx=2, pady=2)

        tk.Label(body, text="// CLICK NODE SETTINGS", bg="#020000", fg=TEXT,
                 font=("Georgia", 16, "bold")).pack(anchor="w")
        tk.Label(body, text=f"TARGET  X={self.action['x']}  Y={self.action['y']}", bg="#020000",
                 fg=CYAN_BRIGHT, font=("Georgia", 9, "bold")).pack(anchor="w", pady=(3, 14))

        tk.Label(body, text="Mouse Button", bg="#020000", fg=TEXT).pack(anchor="w")
        ttk.Combobox(body, textvariable=self.button, values=["left", "right", "middle"],
                     state="readonly").pack(fill="x", pady=(4, 10))

        tk.Label(body, text="Click count", bg="#020000", fg=TEXT).pack(anchor="w")
        tk.Spinbox(body, from_=1, to=100, textvariable=self.clicks).pack(fill="x", pady=(4, 10))

        tk.Label(body, text="Delay after click (seconds)", bg="#020000", fg=TEXT).pack(anchor="w")
        tk.Spinbox(body, from_=0, to=3600, increment=0.1, textvariable=self.delay).pack(fill="x", pady=(4, 13))

        rule = tk.Frame(body, bg="#020000", highlightbackground=RED_SOFT, highlightthickness=1)
        rule.pack(fill="x", pady=(0, 14))
        tk.Label(rule, text="CYCLE RULE  //  AUTO REMOVE", bg="#020000", fg=TEXT,
                 font=("Georgia", 9, "bold")).pack(anchor="w", padx=10, pady=(9, 7))

        r1 = tk.Frame(rule, bg="#020000")
        r1.pack(fill="x", padx=10, pady=3)
        tk.Label(r1, text="Start from cycle", width=22, anchor="w", bg="#020000", fg=TEXT).pack(side="left")
        tk.Spinbox(r1, from_=1, to=999999, textvariable=self.start_cycle, width=10).pack(side="right")

        r2 = tk.Frame(rule, bg="#020000")
        r2.pack(fill="x", padx=10, pady=3)
        tk.Label(r2, text="Remove after cycle", width=22, anchor="w", bg="#020000", fg=TEXT).pack(side="left")
        tk.Spinbox(r2, from_=0, to=999999, textvariable=self.end_cycle, width=10).pack(side="right")

        tk.Label(rule, text="0 = never remove   •   1 = sirf first run me chalega", bg="#020000",
                 fg=CYAN, font=("Georgia", 8)).pack(anchor="w", padx=10, pady=(5, 9))

        tk.Button(body, text="SAVE NODE", bg="#760000", fg=TEXT, activebackground=RED_BRIGHT,
                  activeforeground=TEXT, relief="flat", pady=10, font=("Georgia", 10, "bold"),
                  command=self.save).pack(fill="x")

    def save(self):
        try:
            clicks = max(1, int(self.clicks.get()))
            delay = max(0.0, float(self.delay.get()))
            start_cycle = max(1, int(self.start_cycle.get()))
            end_cycle = max(0, int(self.end_cycle.get()))
            if end_cycle and end_cycle < start_cycle:
                raise ValueError("Remove-after cycle start cycle se chhota nahi ho sakta.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Settings sahi dalo.\n{exc}")
            return

        self.action["button"] = self.button.get()
        self.action["clicks"] = clicks
        self.action["delay"] = delay
        self.action["start_cycle"] = start_cycle
        self.action["end_cycle"] = end_cycle
        self.win.destroy()
        self.callback(self.action)


class ScrollSettings:
    def __init__(self, parent, action, callback):
        self.callback = callback
        self.action = normalize_cycle_rule(dict(action))
        amount = int(self.action.get("amount", -5))

        self.win = tk.Toplevel(parent)
        self.win.title("Scroll Settings")
        self.win.geometry("460x555")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.configure(bg=BG_MAIN)

        self.direction = tk.StringVar(value="up" if amount > 0 else "down")
        self.amount = tk.IntVar(value=abs(amount))
        self.delay = tk.DoubleVar(value=float(self.action.get("delay", 0.5)))
        self.start_cycle = tk.IntVar(value=int(self.action.get("start_cycle", 1)))
        self.end_cycle = tk.IntVar(value=int(self.action.get("end_cycle", 0)))

        outer = tk.Frame(self.win, bg=BG_MAIN, highlightbackground=RED_GLOW, highlightthickness=1)
        outer.pack(fill="both", expand=True, padx=9, pady=9)
        body = tk.Frame(outer, bg="#020000", padx=20, pady=18)
        body.pack(fill="both", expand=True, padx=2, pady=2)

        tk.Label(body, text="// SCROLL NODE SETTINGS", bg="#020000", fg=TEXT,
                 font=("Georgia", 16, "bold")).pack(anchor="w")
        tk.Label(body, text=f"TARGET  X={self.action['x']}  Y={self.action['y']}", bg="#020000",
                 fg=CYAN_BRIGHT, font=("Georgia", 9, "bold")).pack(anchor="w", pady=(3, 14))

        tk.Radiobutton(body, text="↓ Scroll Down", variable=self.direction, value="down",
                       bg="#020000", fg=TEXT, selectcolor=BG_INPUT).pack(anchor="w")
        tk.Radiobutton(body, text="↑ Scroll Up", variable=self.direction, value="up",
                       bg="#020000", fg=TEXT, selectcolor=BG_INPUT).pack(anchor="w")

        tk.Label(body, text="Scroll amount", bg="#020000", fg=TEXT).pack(anchor="w", pady=(10, 0))
        tk.Spinbox(body, from_=1, to=100, textvariable=self.amount).pack(fill="x", pady=(4, 10))
        tk.Label(body, text="Delay after scroll (seconds)", bg="#020000", fg=TEXT).pack(anchor="w")
        tk.Spinbox(body, from_=0, to=3600, increment=0.1, textvariable=self.delay).pack(fill="x", pady=(4, 13))

        rule = tk.Frame(body, bg="#020000", highlightbackground=RED_SOFT, highlightthickness=1)
        rule.pack(fill="x", pady=(0, 14))
        tk.Label(rule, text="CYCLE RULE  //  AUTO REMOVE", bg="#020000", fg=TEXT,
                 font=("Georgia", 9, "bold")).pack(anchor="w", padx=10, pady=(9, 7))
        r1 = tk.Frame(rule, bg="#020000"); r1.pack(fill="x", padx=10, pady=3)
        tk.Label(r1, text="Start from cycle", width=22, anchor="w", bg="#020000", fg=TEXT).pack(side="left")
        tk.Spinbox(r1, from_=1, to=999999, textvariable=self.start_cycle, width=10).pack(side="right")
        r2 = tk.Frame(rule, bg="#020000"); r2.pack(fill="x", padx=10, pady=3)
        tk.Label(r2, text="Remove after cycle", width=22, anchor="w", bg="#020000", fg=TEXT).pack(side="left")
        tk.Spinbox(r2, from_=0, to=999999, textvariable=self.end_cycle, width=10).pack(side="right")
        tk.Label(rule, text="0 = never remove   •   1 = sirf first run me", bg="#020000", fg=CYAN,
                 font=("Georgia", 8)).pack(anchor="w", padx=10, pady=(5, 9))

        tk.Button(body, text="SAVE NODE", bg="#760000", fg=TEXT, activebackground=RED_BRIGHT,
                  activeforeground=TEXT, relief="flat", pady=10, font=("Georgia", 10, "bold"),
                  command=self.save).pack(fill="x")

    def save(self):
        try:
            amount = max(1, int(self.amount.get()))
            delay = max(0.0, float(self.delay.get()))
            start_cycle = max(1, int(self.start_cycle.get()))
            end_cycle = max(0, int(self.end_cycle.get()))
            if end_cycle and end_cycle < start_cycle:
                raise ValueError("Remove-after cycle start cycle se chhota nahi ho sakta.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Settings sahi dalo.\n{exc}")
            return

        self.action["amount"] = amount if self.direction.get() == "up" else -amount
        self.action["delay"] = delay
        self.action["start_cycle"] = start_cycle
        self.action["end_cycle"] = end_cycle
        self.win.destroy()
        self.callback(self.action)


class SwipeSettings:
    def __init__(self, parent, action, callback):
        self.callback = callback
        self.action = normalize_cycle_rule(dict(action))

        self.win = tk.Toplevel(parent)
        self.win.title("Swipe Settings")
        self.win.geometry("470x520")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.configure(bg=BG_MAIN)

        self.duration = tk.DoubleVar(value=float(self.action.get("duration", 0.5)))
        self.delay = tk.DoubleVar(value=float(self.action.get("delay", 0.5)))
        self.start_cycle = tk.IntVar(value=int(self.action.get("start_cycle", 1)))
        self.end_cycle = tk.IntVar(value=int(self.action.get("end_cycle", 0)))

        outer = tk.Frame(self.win, bg=BG_MAIN, highlightbackground=RED_GLOW, highlightthickness=1)
        outer.pack(fill="both", expand=True, padx=9, pady=9)
        body = tk.Frame(outer, bg="#020000", padx=20, pady=18)
        body.pack(fill="both", expand=True, padx=2, pady=2)

        tk.Label(body, text="// SWIPE NODE SETTINGS", bg="#020000", fg=TEXT,
                 font=("Georgia", 16, "bold")).pack(anchor="w")
        tk.Label(body, text=f"START {self.action['x1']},{self.action['y1']}   →   END {self.action['x2']},{self.action['y2']}",
                 bg="#020000", fg=CYAN_BRIGHT, font=("Georgia", 9, "bold")).pack(anchor="w", pady=(3, 14))

        tk.Label(body, text="Swipe duration (seconds)", bg="#020000", fg=TEXT).pack(anchor="w")
        tk.Spinbox(body, from_=0.1, to=30, increment=0.1, textvariable=self.duration).pack(fill="x", pady=(4, 10))
        tk.Label(body, text="Delay after swipe (seconds)", bg="#020000", fg=TEXT).pack(anchor="w")
        tk.Spinbox(body, from_=0, to=3600, increment=0.1, textvariable=self.delay).pack(fill="x", pady=(4, 13))

        rule = tk.Frame(body, bg="#020000", highlightbackground=RED_SOFT, highlightthickness=1)
        rule.pack(fill="x", pady=(0, 14))
        tk.Label(rule, text="CYCLE RULE  //  AUTO REMOVE", bg="#020000", fg=TEXT,
                 font=("Georgia", 9, "bold")).pack(anchor="w", padx=10, pady=(9, 7))
        r1 = tk.Frame(rule, bg="#020000"); r1.pack(fill="x", padx=10, pady=3)
        tk.Label(r1, text="Start from cycle", width=22, anchor="w", bg="#020000", fg=TEXT).pack(side="left")
        tk.Spinbox(r1, from_=1, to=999999, textvariable=self.start_cycle, width=10).pack(side="right")
        r2 = tk.Frame(rule, bg="#020000"); r2.pack(fill="x", padx=10, pady=3)
        tk.Label(r2, text="Remove after cycle", width=22, anchor="w", bg="#020000", fg=TEXT).pack(side="left")
        tk.Spinbox(r2, from_=0, to=999999, textvariable=self.end_cycle, width=10).pack(side="right")
        tk.Label(rule, text="0 = never remove   •   1 = sirf first run me", bg="#020000", fg=CYAN,
                 font=("Georgia", 8)).pack(anchor="w", padx=10, pady=(5, 9))

        tk.Button(body, text="SAVE NODE", bg="#760000", fg=TEXT, activebackground=RED_BRIGHT,
                  activeforeground=TEXT, relief="flat", pady=10, font=("Georgia", 10, "bold"),
                  command=self.save).pack(fill="x")

    def save(self):
        try:
            duration = max(0.1, float(self.duration.get()))
            delay = max(0.0, float(self.delay.get()))
            start_cycle = max(1, int(self.start_cycle.get()))
            end_cycle = max(0, int(self.end_cycle.get()))
            if end_cycle and end_cycle < start_cycle:
                raise ValueError("Remove-after cycle start cycle se chhota nahi ho sakta.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Settings sahi dalo.\n{exc}")
            return

        self.action["duration"] = duration
        self.action["delay"] = delay
        self.action["start_cycle"] = start_cycle
        self.action["end_cycle"] = end_cycle
        self.win.destroy()
        self.callback(self.action)


# ============================================================
# FLOATING TOOLBAR
# ============================================================
class FloatingToolbar:
    """Boxed red-neon toolbar matching the requested screenshot.

    IMPORTANT: Only the toolbar visuals are changed. The smooth target picker,
    exact coordinate locking, automation flow, cycle rules and hotkeys remain
    exactly the same as the ultra-smooth build.
    """
    def __init__(self, app):
        self.app = app

        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANSPARENT_KEY)
        self.win.geometry("82x486+35+180")
        apply_window_colorkey(self.win, TRANSPARENT_KEY, click_through=False, no_activate=False)

        self.drag_x = 0
        self.drag_y = 0
        self._pressed_after = {}

        self.canvas = tk.Canvas(
            self.win,
            width=82,
            height=486,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.buttons = {}

        c = self.canvas

        # =====================================================
        # OUTER DANGER RAIL
        # =====================================================
        # Deep red fake glow -> hard neon edge.
        c.create_rectangle(1, 1, 81, 485, outline="#130000", width=10)
        c.create_rectangle(4, 4, 78, 482, outline="#390000", width=7)
        c.create_rectangle(7, 7, 75, 479, outline="#7a0000", width=4)
        c.create_rectangle(9, 9, 73, 477, outline="#d00000", width=2)
        c.create_rectangle(11, 11, 71, 475, outline="#ff0000", width=1)

        # Top/bottom hot accents.
        c.create_line(14, 10, 36, 10, fill="#ff5050", width=2)
        c.create_line(46, 476, 68, 476, fill="#ff5050", width=2)

        specs = [
            ("play", "▶", self.play_stop),
            ("add", "+", self.add_point),
            ("swipe", "↪", self.add_swipe),
            ("scroll", "↕", self.add_scroll),
            ("remove", "−", self.remove_last),
            ("settings", "⚙", self.open_settings),
            ("move", "✥", None),
        ]

        y = 16
        for key, symbol, command in specs:
            self._make_button(key, symbol, y, command)
            y += 66

        # Move icon itself is the drag handle.
        c.tag_bind("toolbar_move", "<ButtonPress-1>", self.drag_start)
        c.tag_bind("toolbar_move", "<B1-Motion>", self.drag_move)

    def _make_button(self, key, symbol, y, command):
        c = self.canvas
        x1, x2 = 12, 70
        y1, y2 = y, y + 54
        tag = f"toolbar_{key}"

        # Dark visible card. This intentionally matches the screenshot rather
        # than the previous fully-transparent icon-only rail.
        hit = c.create_rectangle(
            x1, y1, x2, y2,
            fill="#050000",
            outline="",
            tags=(tag,)
        )

        # Multi-layer boxed red glow.
        glow3 = c.create_rectangle(
            x1-4, y1-4, x2+4, y2+4,
            outline="#170000", width=7, tags=(tag,)
        )
        glow2 = c.create_rectangle(
            x1-2, y1-2, x2+2, y2+2,
            outline="#4d0000", width=4, tags=(tag,)
        )
        glow1 = c.create_rectangle(
            x1, y1, x2, y2,
            outline="#b00000", width=2, tags=(tag,)
        )
        inner = c.create_rectangle(
            x1+4, y1+4, x2-4, y2-4,
            fill="#070000",
            outline="#ff0000", width=1,
            tags=(tag,)
        )

        # Thin inner hot line, like the user's screenshot.
        hot = c.create_rectangle(
            x1+7, y1+7, x2-7, y2-7,
            outline="#7d0000", width=1,
            tags=(tag,)
        )

        # Right-side cyber chevrons.
        chev1 = c.create_line(
            x2-11, y1+12,
            x2-5, y1+18,
            x2-11, y1+24,
            fill="#720000", width=1, tags=(tag,)
        )
        chev2 = c.create_line(
            x2-11, y1+28,
            x2-5, y1+34,
            x2-11, y1+40,
            fill="#3b0000", width=1, tags=(tag,)
        )

        text_id = c.create_text(
            38,
            (y1+y2)/2,
            text=symbol,
            fill="#ff2020",
            font=("Segoe UI Symbol", 24, "bold"),
            tags=(tag,)
        )

        self.buttons[key] = {
            "tag": tag,
            "hit": hit,
            "text": text_id,
            "g3": glow3,
            "g2": glow2,
            "g1": glow1,
            "inner": inner,
            "hot": hot,
            "chev1": chev1,
            "chev2": chev2,
        }

        def enter(_e):
            # Dangerous red hover glow.
            c.itemconfig(hit, fill="#100000")
            c.itemconfig(glow3, outline="#3a0000")
            c.itemconfig(glow2, outline="#920000")
            c.itemconfig(glow1, outline="#ff0000")
            c.itemconfig(inner, outline="#ff3030", fill="#120000")
            c.itemconfig(hot, outline="#ff0000")
            c.itemconfig(chev1, fill="#ff3030")
            c.itemconfig(chev2, fill="#a00000")
            c.itemconfig(text_id, fill="#ff5050")

        def leave(_e):
            c.itemconfig(hit, fill="#050000")
            c.itemconfig(glow3, outline="#170000")
            c.itemconfig(glow2, outline="#4d0000")
            c.itemconfig(glow1, outline="#b00000")
            c.itemconfig(inner, outline="#ff0000", fill="#070000")
            c.itemconfig(hot, outline="#7d0000")
            c.itemconfig(chev1, fill="#720000")
            c.itemconfig(chev2, fill="#3b0000")
            c.itemconfig(text_id, fill="#ff2020")

        def click(_e):
            # Immediate click flash so the UI never feels delayed.
            c.itemconfig(hit, fill="#2c0000")
            c.itemconfig(glow3, outline="#700000")
            c.itemconfig(glow2, outline="#ff0000")
            c.itemconfig(glow1, outline="#ff5050")
            c.itemconfig(inner, outline="#ff8080", fill="#260000")
            c.itemconfig(hot, outline="#ff4040")
            c.itemconfig(text_id, fill="#ffffff")

            old = self._pressed_after.pop(key, None)
            if old:
                try:
                    self.win.after_cancel(old)
                except Exception:
                    pass

            def release_flash():
                try:
                    c.itemconfig(hit, fill="#100000")
                    c.itemconfig(glow3, outline="#3a0000")
                    c.itemconfig(glow2, outline="#920000")
                    c.itemconfig(glow1, outline="#ff0000")
                    c.itemconfig(inner, outline="#ff3030", fill="#120000")
                    c.itemconfig(hot, outline="#ff0000")
                    c.itemconfig(text_id, fill="#ff5050")
                except Exception:
                    pass
                self._pressed_after.pop(key, None)

            self._pressed_after[key] = self.win.after(75, release_flash)

            if callable(command):
                # Run after the event completes. This keeps the button response
                # instant and avoids sticky/missed Tk mouse events.
                self.win.after_idle(command)

        c.tag_bind(tag, "<Enter>", enter)
        c.tag_bind(tag, "<Leave>", leave)
        if command:
            c.tag_bind(tag, "<Button-1>", click)

    def set_running(self, running):
        try:
            self.canvas.itemconfig(
                self.buttons["play"]["text"],
                text="■" if running else "▶",
                fill="#ff6060" if running else "#ff2020"
            )
        except Exception:
            pass

    def play_stop(self):
        if self.app.running:
            self.app.stop_automation()
        else:
            self.app.start_automation()

    def add_point(self):
        if not self.app.running:
            self.app.add_click_from_toolbar()

    def add_swipe(self):
        if self.app.running:
            return
        if self.app.mode.get() != "multi":
            messagebox.showinfo(APP_NAME, "Swipe Multi Target Mode me use hota hai.")
            return
        self.app.add_swipe_from_toolbar()

    def add_scroll(self):
        if self.app.running:
            return
        if self.app.mode.get() != "multi":
            messagebox.showinfo(APP_NAME, "Scroll Multi Target Mode me use hota hai.")
            return
        self.app.add_scroll_from_toolbar()

    def remove_last(self):
        if self.app.running:
            return
        if self.app.mode.get() == "single":
            self.app.single_action = None
        elif self.app.actions:
            self.app.actions.pop()
        self.app.draw_markers()
        self.app.refresh_main_info()

    def open_settings(self):
        self.app.show_main()

    def drag_start(self, event):
        self.drag_x = event.x_root - self.win.winfo_x()
        self.drag_y = event.y_root - self.win.winfo_y()

    def drag_move(self, event):
        x = event.x_root - self.drag_x
        y = event.y_root - self.drag_y
        self.win.geometry(f"+{x}+{y}")

    def destroy(self):
        for after_id in list(self._pressed_after.values()):
            try:
                self.win.after_cancel(after_id)
            except Exception:
                pass
        self._pressed_after.clear()
        try:
            self.win.destroy()
        except Exception:
            pass


# NEON CANVAS BUTTON
# ============================================================
class NeonButton(tk.Canvas):
    """Tkinter canvas button with a CSS-like multi-layer neon border."""
    def __init__(self, parent, text, command=None, accent=False, height=42, font_size=9):
        self._bg = "#010000"
        super().__init__(
            parent,
            height=height,
            bg=self._bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2"
        )
        self.text = text
        self.command = command
        self.accent = accent
        self.font_size = font_size
        self.hover = False
        self.bind("<Configure>", self._draw)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

    def _enter(self, _event=None):
        self.hover = True
        self._draw()

    def _leave(self, _event=None):
        self.hover = False
        self._draw()

    def _click(self, _event=None):
        if callable(self.command):
            self.command()

    def _draw(self, _event=None):
        self.delete("all")
        w = max(10, self.winfo_width())
        h = max(10, self.winfo_height())

        if self.accent:
            fill = "#320000" if not self.hover else "#650000"
            text_color = TEXT
        else:
            fill = "#020000" if not self.hover else "#120000"
            text_color = TEXT

        # soft glow / double border
        self.create_rectangle(1, 1, w - 2, h - 2, outline="#210000", width=4)
        self.create_rectangle(3, 3, w - 4, h - 4, outline="#770000", width=2)
        self.create_rectangle(5, 5, w - 6, h - 6, outline=RED_BRIGHT if self.hover or self.accent else RED_LIGHT, width=1, fill=fill)

        # tiny corner cuts / cyber highlights
        c = 11
        col = RED_GLOW if self.hover else RED_BRIGHT
        self.create_line(5, 5, c + 5, 5, fill=col, width=2)
        self.create_line(5, 5, 5, c + 5, fill=col, width=2)
        self.create_line(w - 6, h - 6, w - c - 6, h - 6, fill=col, width=2)
        self.create_line(w - 6, h - 6, w - 6, h - c - 6, fill=col, width=2)

        self.create_text(
            w / 2,
            h / 2,
            text=self.text,
            fill=text_color,
            font=("Georgia", self.font_size, "bold")
        )


# ============================================================
# MAIN APP
# ============================================================
class AutoClickerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1240x790")
        self.root.minsize(1240, 790)
        self.root.maxsize(1240, 790)
        self.root.configure(bg=BG_MAIN)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)

        # Window/taskbar icon from AutoClicker.jpg. PyInstaller uses the generated
        # AutoClicker.ico for the EXE icon; this keeps the Tk window icon matched.
        self._app_icon_photo = None
        if PIL_AVAILABLE and os.path.exists(APP_ICON_IMAGE):
            try:
                _icon_img = Image.open(APP_ICON_IMAGE).convert("RGBA")
                _icon_img.thumbnail((256, 256), Image.Resampling.LANCZOS)
                self._app_icon_photo = ImageTk.PhotoImage(_icon_img)
                self.root.iconphoto(True, self._app_icon_photo)
            except Exception:
                self._app_icon_photo = None

        # Global widget defaults: black/red neon with green terminal text.
        self.root.option_add("*Background", BG_CARD)
        self.root.option_add("*Foreground", TEXT)
        self.root.option_add("*Font", ("Georgia", 9))
        self.root.option_add("*Entry.background", BG_INPUT)
        self.root.option_add("*Entry.foreground", TEXT)
        self.root.option_add("*Entry.insertBackground", RED_LIGHT)
        self.root.option_add("*Spinbox.background", BG_INPUT)
        self.root.option_add("*Spinbox.foreground", TEXT)
        self.root.option_add("*Spinbox.insertBackground", RED_LIGHT)
        self.root.option_add("*Button.background", "#050000")
        self.root.option_add("*Button.foreground", TEXT)
        self.root.option_add("*Button.activeBackground", "#180000")
        self.root.option_add("*Button.activeForeground", TEXT)
        self.root.option_add("*Radiobutton.background", BG_CARD)
        self.root.option_add("*Radiobutton.foreground", TEXT)
        self.root.option_add("*Radiobutton.selectColor", BG_INPUT)
        self.root.option_add("*Checkbutton.background", BG_CARD)
        self.root.option_add("*Checkbutton.foreground", TEXT)
        self.root.option_add("*Checkbutton.selectColor", BG_INPUT)
        self.root.option_add("*Listbox.background", BG_INPUT)
        self.root.option_add("*Listbox.foreground", TEXT)
        self.root.option_add("*Listbox.selectBackground", RED_SOFT)
        self.root.option_add("*Listbox.selectForeground", TEXT)

        self.mode = tk.StringVar(value="single")
        self.single_action = None
        self.actions = []

        self.running = False
        self.paused = False
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.worker = None

        self.toolbar = None
        self.markers = []

        # UI-only animation references.
        self.bg_animation = None
        self.hero_animation = None
        self.side_animation = None

        # Run settings
        self.loop_mode = tk.StringVar(value="infinite")
        self.duration_seconds = tk.IntVar(value=300)
        self.cycles = tk.IntVar(value=10)
        self.cycle_delay = tk.DoubleVar(value=0.0)

        # Global hotkeys
        self.start_hotkey = tk.StringVar(value="F7")
        self.pause_hotkey = tk.StringVar(value="F9")
        self.stop_hotkey = tk.StringVar(value="F8")
        self.hotkey_listener = None

        self.event_queue = queue.Queue()

        # ttk widgets: black/red palette.
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", font=("Georgia", 9))
        style.configure(
            "TCombobox",
            fieldbackground=BG_INPUT,
            background=BG_INPUT,
            foreground=TEXT,
            arrowcolor=RED_LIGHT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER
        )

        self.build_ui()
        self.root.after(80, self.process_events)
        self.root.after(200, lambda: self.register_hotkeys(show_message=False))

    # ========================================================
    # UI
    # ========================================================
    def build_ui(self):
        """Red-neon / green-terminal transparent hacker dashboard.

        The complete automation workflow is unchanged. Only the main UI is
        redrawn on one Canvas so that the GIF can remain visible behind
        semi-transparent/stippled panels.
        """
        # ----------------------------------------------------
        # DESIGN TOKENS / SPACING
        # ----------------------------------------------------
        W, H = 1240, 790
        PAD = 24
        GAP = 18
        HEADER_H = 68
        SIDE_W = 246
        CONTENT_X = PAD + SIDE_W + GAP
        CONTENT_W = W - CONTENT_X - PAD
        BODY_Y = PAD + HEADER_H + GAP
        BODY_H = H - BODY_Y - PAD

        self.root.configure(bg="#000000")

        canvas = tk.Canvas(
            self.root,
            width=W,
            height=H,
            bg="#000000",
            highlightthickness=0,
            bd=0
        )
        canvas.pack(fill="both", expand=True)
        self.dashboard_canvas = canvas

        # Main background GIF behind the working area. No filename is shown.
        main_gif = first_existing_gif(GIF_MAIN, GIF_ALT)
        self.canvas_bg_animation = CanvasGifPlayer(
            canvas,
            main_gif,
            CONTENT_X,
            BODY_Y,
            CONTENT_W,
            BODY_H,
            brightness=0.56,
            crop=True,
            min_delay=80,
        )

        # Side GIF is a second independent live feed, also with no filename.
        side_gif = first_existing_gif(GIF_ALT, GIF_MAIN)
        self.canvas_side_animation = CanvasGifPlayer(
            canvas,
            side_gif,
            PAD + 14,
            BODY_Y + 28,
            SIDE_W - 28,
            174,
            brightness=0.90,
            crop=True,
            min_delay=80,
        )

        # ----------------------------------------------------
        # BACKGROUND FINISH
        # ----------------------------------------------------
        # Keep the animated GIF visible, but calm it down with a light
        # transparent black veil and a sparse red cyber grid.  This makes
        # the glass panels/readable text look cleaner without changing any
        # automation or clock behaviour.
        canvas.create_rectangle(
            CONTENT_X, BODY_Y, CONTENT_X + CONTENT_W, BODY_Y + BODY_H,
            fill="#000000", stipple="gray12", outline=""
        )
        for gx in range(CONTENT_X + 24, CONTENT_X + CONTENT_W, 64):
            canvas.create_line(gx, BODY_Y, gx, BODY_Y + BODY_H, fill="#190000", width=1)
        for gy in range(BODY_Y + 24, BODY_Y + BODY_H, 64):
            canvas.create_line(CONTENT_X, gy, CONTENT_X + CONTENT_W, gy, fill="#190000", width=1)
        canvas.create_rectangle(
            CONTENT_X + 4, BODY_Y + 4, CONTENT_X + CONTENT_W - 4, BODY_Y + BODY_H - 4,
            outline="#2b0000", width=1
        )
        # Sparse terminal-green traces over the live GIF.
        for gy in range(BODY_Y + 38, BODY_Y + BODY_H - 20, 116):
            canvas.create_line(CONTENT_X + 14, gy, CONTENT_X + CONTENT_W - 14, gy, fill="#063d1f", width=1)
        for gx in range(CONTENT_X + 42, CONTENT_X + CONTENT_W - 20, 148):
            canvas.create_line(gx, BODY_Y + 14, gx, BODY_Y + BODY_H - 14, fill="#042814", width=1)

        # ----------------------------------------------------
        # CANVAS HELPERS
        # ----------------------------------------------------
        def glass_rect(x1, y1, x2, y2, radius=0, strong=False):
            # Transparent-looking black glass: the GIF remains visible through
            # the stippled fill, while multiple pure-red rings simulate a
            # CSS neon box-shadow.
            fill = "#000000"
            stipple = "gray25" if strong else "gray12"

            # Wide low-intensity halo -> hot inner edge.
            canvas.create_rectangle(x1-8, y1-8, x2+8, y2+8, outline="#120000", width=8)
            canvas.create_rectangle(x1-6, y1-6, x2+6, y2+6, outline="#2d0000", width=6)
            canvas.create_rectangle(x1-4, y1-4, x2+4, y2+4, outline="#620000", width=4)
            canvas.create_rectangle(x1-2, y1-2, x2+2, y2+2, outline="#b00000", width=2)
            canvas.create_rectangle(
                x1, y1, x2, y2,
                fill=fill, stipple=stipple,
                outline="#ff0000", width=2
            )
            canvas.create_rectangle(x1+5, y1+5, x2-5, y2-5, outline="#ff1010", width=1)
            canvas.create_rectangle(x1+9, y1+9, x2-9, y2-9, outline="#4e0000", width=1)

            # Sharp cyber corner brackets.
            c = 18
            for coords in (
                (x1+3, y1+3, x1+c, y1+3), (x1+3, y1+3, x1+3, y1+c),
                (x2-c, y1+3, x2-3, y1+3), (x2-3, y1+3, x2-3, y1+c),
                (x1+3, y2-3, x1+c, y2-3), (x1+3, y2-c, x1+3, y2-3),
                (x2-c, y2-3, x2-3, y2-3), (x2-3, y2-c, x2-3, y2-3),
            ):
                canvas.create_line(*coords, fill="#ff0000", width=2)

        def section_label(x, y, text, line_to):
            canvas.create_text(
                x, y,
                text=text,
                anchor="w",
                fill=TEXT,
                font=("Georgia", 10, "bold")
            )
            canvas.create_line(x + 145, y, line_to, y, fill="#750000", width=1)
            canvas.create_rectangle(x - 15, y - 3, x - 8, y + 3, fill=RED_BRIGHT, outline="")

        self._canvas_buttons = []

        def button(x1, y1, x2, y2, text, command, accent=False, small=False):
            tag = f"btn_{len(self._canvas_buttons)}"
            base_fill = "#200000" if accent else "#000000"
            hover_fill = "#600000" if accent else "#170000"
            font = ("Georgia", 9 if not small else 8, "bold")

            # CSS-like neon halo using layered rectangles.
            halo3 = canvas.create_rectangle(x1-7, y1-7, x2+7, y2+7, outline="#120000", width=7, tags=(tag,))
            halo2 = canvas.create_rectangle(x1-5, y1-5, x2+5, y2+5, outline="#350000", width=5, tags=(tag,))
            halo1 = canvas.create_rectangle(x1-3, y1-3, x2+3, y2+3, outline="#760000", width=3, tags=(tag,))
            outer = canvas.create_rectangle(x1, y1, x2, y2, outline="#ff0000", width=2, tags=(tag,))
            inner = canvas.create_rectangle(
                x1+4, y1+4, x2-4, y2-4,
                fill=base_fill,
                stipple="gray12",
                outline="#ff1010", width=1,
                tags=(tag,)
            )
            text_id = canvas.create_text(
                (x1+x2)/2, (y1+y2)/2,
                text=text, fill=TEXT, font=font, tags=(tag,)
            )

            c = 11
            for coords in (
                (x1+4, y1+4, x1+c, y1+4), (x1+4, y1+4, x1+4, y1+c),
                (x2-c, y1+4, x2-4, y1+4), (x2-4, y1+4, x2-4, y1+c),
                (x1+4, y2-4, x1+c, y2-4), (x1+4, y2-c, x1+4, y2-4),
                (x2-c, y2-4, x2-4, y2-4), (x2-4, y2-c, x2-4, y2-4),
            ):
                canvas.create_line(*coords, fill="#ff0000", width=1, tags=(tag,))

            def enter(_e):
                canvas.itemconfig(inner, fill=hover_fill, outline="#ff3030")
                canvas.itemconfig(outer, outline="#ff3030")
                canvas.itemconfig(halo3, outline="#360000")
                canvas.itemconfig(halo2, outline="#750000")
                canvas.itemconfig(halo1, outline="#e00000")
                canvas.itemconfig(text_id, fill=TEXT)

            def leave(_e):
                canvas.itemconfig(inner, fill=base_fill, outline="#ff1010")
                canvas.itemconfig(outer, outline="#ff0000")
                canvas.itemconfig(halo3, outline="#120000")
                canvas.itemconfig(halo2, outline="#350000")
                canvas.itemconfig(halo1, outline="#760000")

            def click(_e):
                if callable(command):
                    command()

            canvas.tag_bind(tag, "<Enter>", enter)
            canvas.tag_bind(tag, "<Leave>", leave)
            canvas.tag_bind(tag, "<Button-1>", click)
            self._canvas_buttons.append(tag)
            return tag

        # ----------------------------------------------------
        # HEADER — intentionally minimal
        # ----------------------------------------------------
        hx1, hy1, hx2, hy2 = PAD, PAD, W-PAD, PAD+HEADER_H
        glass_rect(hx1, hy1, hx2, hy2, strong=True)
        canvas.create_text(
            hx1+24, hy1+25,
            text="AUTOCLICK",
            anchor="w",
            fill=TEXT,
            font=("Georgia", 21, "bold")
        )
        canvas.create_text(
            hx1+26, hy1+49,
            text="AUTOMATION  /  SEQUENCE CONTROL",
            anchor="w",
            fill=TEXT_SOFT,
            font=("Georgia", 8, "bold")
        )
        self.canvas_status_id = canvas.create_text(
            hx2-24, (hy1+hy2)/2,
            text="● READY",
            anchor="e",
            fill=TEXT,
            font=("Georgia", 9, "bold")
        )

        # ----------------------------------------------------
        # SIDEBAR
        # ----------------------------------------------------
        sx1, sy1, sx2, sy2 = PAD, BODY_Y, PAD+SIDE_W, BODY_Y+BODY_H
        glass_rect(sx1, sy1, sx2, sy2, strong=False)

        # side GIF frame glow only; GIF itself remains visible
        gx1, gy1 = sx1+14, sy1+28
        gx2, gy2 = sx2-14, gy1+174
        canvas.create_rectangle(gx1-3, gy1-3, gx2+3, gy2+3, outline="#2c0000", width=5)
        canvas.create_rectangle(gx1, gy1, gx2, gy2, outline=RED_BRIGHT, width=1)
        canvas.create_line(gx1, (gy1+gy2)/2, gx2, (gy1+gy2)/2, fill="#e00000", width=1)

        section_label(sx1+34, gy2+36, "CONTROL", sx2-18)

        nav_x1 = sx1+16
        nav_x2 = sx2-16
        nav_y = gy2+58
        nav_h = 46
        button(nav_x1, nav_y, nav_x2, nav_y+nav_h, "SINGLE TARGET", lambda: self.open_mode_settings("single"), accent=True)
        nav_y += nav_h+10
        button(nav_x1, nav_y, nav_x2, nav_y+nav_h, "MULTI ACTIONS", self.open_action_list)
        nav_y += nav_h+10
        button(nav_x1, nav_y, nav_x2, nav_y+nav_h, "RUN SETTINGS", self.open_common_settings)
        nav_y += nav_h+10
        button(nav_x1, nav_y, nav_x2, nav_y+nav_h, "SAVED CONFIGS", self.manage_configs)

        # ----------------------------------------------------
        # MINI CYBER WATCH / HUD
        # Sits only in the empty area below CONTROL buttons.
        # No workflow logic is changed; this is visual + live status only.
        # ----------------------------------------------------
        watch_cx = (sx1 + sx2) / 2
        watch_cy = sy2 - 92
        r = 80

        # diffuse glow rings
        canvas.create_oval(watch_cx-r-8, watch_cy-r-8, watch_cx+r+8, watch_cy+r+8, outline="#150000", width=7)
        canvas.create_oval(watch_cx-r-5, watch_cy-r-5, watch_cx+r+5, watch_cy+r+5, outline="#3a0000", width=5)
        canvas.create_oval(watch_cx-r-2, watch_cy-r-2, watch_cx+r+2, watch_cy+r+2, outline="#760000", width=3)
        canvas.create_oval(watch_cx-r, watch_cy-r, watch_cx+r, watch_cy+r, outline=RED_BRIGHT, width=1)
        canvas.create_oval(watch_cx-r+6, watch_cy-r+6, watch_cx+r-6, watch_cy+r-6, outline="#8f0000", width=1)
        canvas.create_oval(watch_cx-r+12, watch_cy-r+12, watch_cx+r-12, watch_cy+r-12, outline="#310000", width=1)

        # Segmented warning arcs make the clock feel more like a cyber HUD.
        for start_angle in (8, 52, 98, 144, 188, 234, 280, 326):
            canvas.create_arc(
                watch_cx-r-3, watch_cy-r-3, watch_cx+r+3, watch_cy+r+3,
                start=start_angle, extent=22, style="arc", outline="#ff2020", width=3
            )

        # radial ticks like the reference cyber watch
        import math as _watch_math
        for i in range(36):
            a = _watch_math.radians(i * 10 - 90)
            tick_outer = r - 7
            tick_inner = r - (13 if i % 3 == 0 else 10)
            x1 = watch_cx + _watch_math.cos(a) * tick_inner
            y1 = watch_cy + _watch_math.sin(a) * tick_inner
            x2 = watch_cx + _watch_math.cos(a) * tick_outer
            y2 = watch_cy + _watch_math.sin(a) * tick_outer
            canvas.create_line(x1, y1, x2, y2, fill="#ff0000" if i % 3 == 0 else "#650000", width=1)

        canvas.create_text(
            watch_cx, watch_cy-r+18,
            text="CYBER // LINK",
            fill=TEXT_SOFT,
            font=("Georgia", 7, "bold")
        )
        self.canvas_watch_time_id = canvas.create_text(
            watch_cx, watch_cy-18,
            text="00:00",
            fill=TEXT,
            font=("Georgia", 25, "bold")
        )
        self.canvas_watch_mode_id = canvas.create_text(
            watch_cx, watch_cy+13,
            text="MODE  SINGLE",
            fill=TEXT,
            font=("Georgia", 8, "bold")
        )
        self.canvas_watch_actions_id = canvas.create_text(
            watch_cx, watch_cy+32,
            text="ACTIONS  0",
            fill=TEXT_SOFT,
            font=("Georgia", 8, "bold")
        )
        self.canvas_watch_status_id = canvas.create_text(
            watch_cx, watch_cy+51,
            text="● READY",
            fill=TEXT,
            font=("Georgia", 7, "bold")
        )

        self.canvas_sidebar_state_id = canvas.create_text(
            (sx1+sx2)/2, sy2-18,
            text="SINGLE  •  0 ACTIONS  •  MANUAL",
            anchor="center",
            fill=TEXT_MUTED,
            font=("Georgia", 8, "bold"),
            state="hidden"
        )

        # ----------------------------------------------------
        # MAIN HERO — no giant warning/HUD clutter
        # ----------------------------------------------------
        mx1, my1, mx2, my2 = CONTENT_X, BODY_Y, CONTENT_X+CONTENT_W, BODY_Y+BODY_H
        hero_x1 = mx1+22
        hero_y1 = my1+24
        hero_x2 = mx2-22
        hero_y2 = hero_y1+136
        glass_rect(hero_x1, hero_y1, hero_x2, hero_y2, strong=False)

        canvas.create_text(
            hero_x1+28, hero_y1+35,
            text="AUTOMATION // CONTROL",
            anchor="w",
            fill=TEXT,
            font=("Georgia", 8, "bold")
        )
        canvas.create_text(
            hero_x1+28, hero_y1+72,
            text="AUTOCLICK",
            anchor="w",
            fill=TEXT,
            font=("Georgia", 28, "bold")
        )
        canvas.create_line(hero_x1+28, hero_y1+101, hero_x2-28, hero_y1+101, fill="#7d0000", width=1)

        self.canvas_hero_mode_id = canvas.create_text(
            hero_x1+30, hero_y1+116,
            text="MODE  SINGLE",
            anchor="w",
            fill=TEXT,
            font=("Georgia", 8, "bold")
        )
        self.canvas_hero_actions_id = canvas.create_text(
            hero_x1+205, hero_y1+116,
            text="ACTIONS  0",
            anchor="w",
            fill=TEXT_SOFT,
            font=("Georgia", 8, "bold")
        )
        self.canvas_hero_loop_id = canvas.create_text(
            hero_x1+370, hero_y1+116,
            text="LOOP  MANUAL",
            anchor="w",
            fill=TEXT_SOFT,
            font=("Georgia", 8, "bold")
        )

        # ----------------------------------------------------
        # MAIN TWO-COLUMN CARDS
        # ----------------------------------------------------
        cards_top = hero_y2 + GAP
        cards_bottom = my2 - 174
        left_x1 = hero_x1
        left_x2 = hero_x1 + 570
        right_x1 = left_x2 + GAP
        right_x2 = hero_x2

        glass_rect(left_x1, cards_top, left_x2, cards_bottom, strong=False)
        glass_rect(right_x1, cards_top, right_x2, cards_bottom, strong=False)

        section_label(left_x1+34, cards_top+34, "AUTOMATION MODE", left_x2-24)
        section_label(right_x1+34, cards_top+34, "RUN CONTROL", right_x2-24)

        # Single target row
        row1_y = cards_top+64
        canvas.create_text(left_x1+36, row1_y+18, text="01  SINGLE TARGET", anchor="w", fill=TEXT, font=("Georgia", 10, "bold"))
        button(left_x1+34, row1_y+40, left_x1+282, row1_y+84, "SET TARGET", lambda: self.open_mode_settings("single"))
        button(left_x1+294, row1_y+40, left_x2-34, row1_y+84, "ENABLE", lambda: self.enable_mode("single"), accent=True)

        canvas.create_line(left_x1+34, row1_y+102, left_x2-34, row1_y+102, fill="#5b0000", width=1)

        # Multi row
        row2_y = row1_y+116
        canvas.create_text(left_x1+36, row2_y+18, text="02  MULTI ACTIONS", anchor="w", fill=TEXT, font=("Georgia", 10, "bold"))
        button(left_x1+34, row2_y+40, left_x1+282, row2_y+84, "MANAGE", self.open_action_list)
        button(left_x1+294, row2_y+40, left_x2-34, row2_y+84, "ENABLE", lambda: self.enable_mode("multi"), accent=True)

        # Run buttons
        run_y = cards_top+66
        button(right_x1+34, run_y, right_x2-34, run_y+54, "▶  START", self.start_automation, accent=True)
        button(right_x1+34, run_y+68, (right_x1+right_x2)//2-6, run_y+112, "Ⅱ  PAUSE", self.toggle_pause)
        button((right_x1+right_x2)//2+6, run_y+68, right_x2-34, run_y+112, "■  STOP", self.stop_automation)

        canvas.create_line(right_x1+34, run_y+132, right_x2-34, run_y+132, fill="#5b0000", width=1)
        canvas.create_text(right_x1+36, run_y+154, text="LOOP / CYCLE", anchor="w", fill=TEXT, font=("Georgia", 9, "bold"))
        self.canvas_loop_state_id = canvas.create_text(right_x2-36, run_y+154, text="MANUAL STOP", anchor="e", fill=TEXT, font=("Georgia", 8, "bold"))
        button(right_x1+34, run_y+172, right_x2-34, run_y+216, "CHANGE RUN SETTINGS", self.open_common_settings)

        # ----------------------------------------------------
        # CONFIG FOOTER
        # ----------------------------------------------------
        config_y1 = my2-154
        config_y2 = my2-22
        glass_rect(hero_x1, config_y1, hero_x2, config_y2, strong=False)
        section_label(hero_x1+34, config_y1+30, "SCRIPT / CONFIG", hero_x2-24)

        bx1 = hero_x1+34
        bx2 = hero_x2-34
        bgap = 10
        bw = (bx2-bx1 - bgap*3)/4
        labels = (
            ("SAVE", self.save_current_config, True),
            ("SAVED LIST", self.manage_configs, False),
            ("IMPORT", self.import_script, False),
            ("EXPORT", self.export_script, False),
        )
        x = bx1
        for label, command, accent in labels:
            button(x, config_y1+50, x+bw, config_y1+92, label, command, accent=accent, small=True)
            x += bw+bgap

        self.canvas_hotkeys_id = canvas.create_text(
            hero_x1+34, config_y2-18,
            text="",
            anchor="w",
            fill=TEXT_SOFT,
            font=("Georgia", 8)
        )

        # Root-level subtle red scan lines for cyber depth, kept sparse.
        for y in range(BODY_Y+12, H-PAD, 82):
            canvas.create_line(CONTENT_X+8, y, W-PAD-8, y, fill="#150000", width=1)
            canvas.tag_lower(canvas.find_all()[-1])

        self.refresh_main_info()
        self.update_cyber_watch()

    def update_cyber_watch(self):
        """Refresh only the decorative sidebar cyber watch once per second."""
        try:
            if not hasattr(self, "dashboard_canvas"):
                return
            now = time.strftime("%H:%M")
            c = self.dashboard_canvas
            c.itemconfig(self.canvas_watch_time_id, text=now)

            mode_name = self.mode.get().upper()
            action_count = (
                (1 if self.single_action else 0)
                if self.mode.get() == "single"
                else len(self.actions)
            )
            c.itemconfig(self.canvas_watch_mode_id, text=f"MODE  {mode_name}")
            c.itemconfig(self.canvas_watch_actions_id, text=f"ACTIONS  {action_count}")

            if self.running and self.paused:
                watch_text, watch_color = "● PAUSED", TEXT_SOFT
            elif self.running:
                watch_text, watch_color = "● RUNNING", TEXT
            else:
                watch_text, watch_color = "● READY", TEXT
            c.itemconfig(self.canvas_watch_status_id, text=watch_text, fill=watch_color)
        except Exception:
            pass
        finally:
            try:
                self.root.after(1000, self.update_cyber_watch)
            except Exception:
                pass

    def make_card(self, parent, title, mode):
        card = tk.Frame(
            parent,
            bg="#020000",
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0
        )

        head = tk.Frame(card, bg="#070000")
        head.pack(fill="x")

        tk.Label(
            head,
            text=title,
            bg="#070000",
            fg=TEXT,
            font=("Georgia", 10, "bold"),
            anchor="w"
        ).pack(side="left", padx=13, pady=9)

        tk.Label(
            head,
            text="READY",
            bg="#070000",
            fg=TEXT,
            font=("Georgia", 8, "bold")
        ).pack(side="right", padx=12)

        body = tk.Frame(card, bg="#020000")
        body.pack(fill="x", padx=10, pady=9)

        tk.Button(
            body,
            text="⚙  SETTINGS",
            anchor="w",
            relief="flat",
            bg="#050000",
            fg=TEXT,
            activebackground="#180000",
            activeforeground=RED_BRIGHT,
            font=("Georgia", 9),
            padx=10,
            pady=8,
            command=lambda: self.open_mode_settings(mode)
        ).pack(fill="x", pady=2)

        tk.Button(
            body,
            text="ⓘ  INSTRUCTIONS",
            anchor="w",
            relief="flat",
            bg="#050000",
            fg=TEXT_SOFT,
            activebackground="#180000",
            activeforeground=TEXT,
            font=("Georgia", 9),
            padx=10,
            pady=8,
            command=lambda: self.show_instructions(mode)
        ).pack(fill="x", pady=2)

        if mode == "multi":
            tk.Button(
                body,
                text="✥  MANAGE ACTIONS",
                anchor="w",
                relief="flat",
                bg="#050000",
                fg=CYAN_BRIGHT,
                activebackground="#180000",
                activeforeground=CYAN_BRIGHT,
                font=("Georgia", 9, "bold"),
                padx=10,
                pady=8,
                command=self.open_action_list
            ).pack(fill="x", pady=2)

        tk.Button(
            body,
            text="▶  ENABLE MODE",
            bg="#760000",
            fg=TEXT,
            activebackground=RED_BRIGHT,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=("Georgia", 10, "bold"),
            pady=10,
            command=lambda: self.enable_mode(mode)
        ).pack(fill="x", pady=(8, 1))

        return card

    def refresh_main_info(self):
        if self.loop_mode.get() == "cycles":
            stop_info = f"{self.cycles.get()} cycles"
            loop_short = f"{self.cycles.get()} CYCLES"
        elif self.loop_mode.get() == "time":
            stop_info = f"{self.duration_seconds.get()} seconds"
            loop_short = f"{self.duration_seconds.get()} SEC"
        else:
            stop_info = "Manual stop"
            loop_short = "MANUAL"

        mode_name = self.mode.get().upper()
        action_count = (
            (1 if self.single_action else 0)
            if self.mode.get() == "single"
            else len(self.actions)
        )


        # Canvas dashboard values (new clean transparent UI).
        if hasattr(self, "dashboard_canvas"):
            try:
                c = self.dashboard_canvas
                c.itemconfig(self.canvas_sidebar_state_id, text=f"{mode_name}  •  {action_count} ACTIONS  •  {loop_short}")
                c.itemconfig(self.canvas_hero_mode_id, text=f"MODE  {mode_name}")
                c.itemconfig(self.canvas_hero_actions_id, text=f"ACTIONS  {action_count}")
                c.itemconfig(self.canvas_hero_loop_id, text=f"LOOP  {loop_short}")
                c.itemconfig(self.canvas_loop_state_id, text=stop_info.upper())
                c.itemconfig(
                    self.canvas_hotkeys_id,
                    text=(f"HOTKEYS   START {self.start_hotkey.get()}   /   "
                          f"PAUSE {self.pause_hotkey.get()}   /   STOP {self.stop_hotkey.get()}")
                )
                if self.running and self.paused:
                    status_text, status_color = "● PAUSED", "#ff5a5a"
                elif self.running:
                    status_text, status_color = "● RUNNING", RED_BRIGHT
                else:
                    status_text, status_color = "● READY", "#ff3030"
                c.itemconfig(self.canvas_status_id, text=status_text, fill=status_color)
                if hasattr(self, "canvas_watch_mode_id"):
                    c.itemconfig(self.canvas_watch_mode_id, text=f"MODE  {mode_name}")
                    c.itemconfig(self.canvas_watch_actions_id, text=f"ACTIONS  {action_count}")
                    if self.running and self.paused:
                        c.itemconfig(self.canvas_watch_status_id, text="● PAUSED", fill=TEXT_SOFT)
                    elif self.running:
                        c.itemconfig(self.canvas_watch_status_id, text="● RUNNING", fill=TEXT)
                    else:
                        c.itemconfig(self.canvas_watch_status_id, text="● READY", fill=TEXT)
            except Exception:
                pass

        # New minimal dashboard labels.
        if hasattr(self, "dashboard_state"):
            self.dashboard_state.config(
                text=f"{mode_name}  •  {action_count} ACTIONS  •  {loop_short}"
            )

        if hasattr(self, "loop_state_label"):
            self.loop_state_label.config(text=stop_info.upper())

        if hasattr(self, "hotkey_line"):
            self.hotkey_line.config(
                text=(
                    f"HOTKEYS   START {self.start_hotkey.get()}   /   "
                    f"PAUSE {self.pause_hotkey.get()}   /   STOP {self.stop_hotkey.get()}"
                )
            )

        # Backward-compatible labels used by older UI versions / dialogs.
        if hasattr(self, "info_label"):
            self.info_label.config(
                text=(
                    f"START KEY : {self.start_hotkey.get()}\n"
                    f"PAUSE KEY : {self.pause_hotkey.get()}\n"
                    f"STOP KEY  : {self.stop_hotkey.get()}\n"
                    f"RUN MODE  : {stop_info}\n"
                    f"CYCLE GAP : {self.cycle_delay.get()} sec"
                )
            )

        if hasattr(self, "hero_mode_label"):
            self.hero_mode_label.config(text=f"MODE       {mode_name}")
        if hasattr(self, "hero_action_label"):
            self.hero_action_label.config(text=f"ACTIONS    {action_count}")
        if hasattr(self, "hero_loop_label"):
            self.hero_loop_label.config(text=f"LOOP       {loop_short}")
        if hasattr(self, "sidebar_status"):
            self.sidebar_status.config(
                text=f"READY\nMODE: {mode_name}\nACTIONS: {action_count}"
            )

        # Circular HUD + system card values are real application state.
        if hasattr(self, "hud_canvas"):
            try:
                self.hud_canvas.itemconfig(self.hud_mode_id, text=f"MODE  {mode_name}")
                self.hud_canvas.itemconfig(self.hud_actions_id, text=f"ACTIONS  {action_count}")
                self.hud_canvas.itemconfig(self.hud_loop_id, text=f"LOOP  {loop_short}")
                if self.running and self.paused:
                    hud_state, hud_color = "PAUSED", "#ff5a5a"
                elif self.running:
                    hud_state, hud_color = "RUNNING", RED_BRIGHT
                else:
                    hud_state, hud_color = "READY", "#ff3030"
                self.hud_canvas.itemconfig(self.hud_run_id, text=f"STATUS  {hud_state}", fill=hud_color)
            except Exception:
                pass

        if hasattr(self, "alert_canvas") and hasattr(self, "alert_status_id"):
            try:
                if self.running and self.paused:
                    alert_text, alert_color = "PAUSED // EXECUTION HELD", "#ff5a5a"
                elif self.running:
                    alert_text, alert_color = f"RUNNING // {action_count} ACTIONS", RED_BRIGHT
                else:
                    alert_text, alert_color = f"READY // {mode_name} // {action_count} ACTIONS", "#ff3030"
                self.alert_canvas.itemconfig(self.alert_status_id, text=alert_text, fill=alert_color)
            except Exception:
                pass

        if hasattr(self, "top_status"):
            if self.running and not self.paused:
                self.top_status.config(text="● RUNNING", fg=TEXT)
            elif self.running and self.paused:
                self.top_status.config(text="● PAUSED", fg=TEXT_SOFT)
            else:
                self.top_status.config(text="● READY", fg=TEXT)

    def enable_mode(self, mode):
        if self.running:
            return

        self.mode.set(mode)

        if mode == "single" and not self.single_action:
            self.pick_single_action(open_toolbar_after=True)
            return

        self.create_toolbar()
        self.root.withdraw()
        self.draw_markers()

    def create_toolbar(self):
        if self.toolbar:
            self.toolbar.destroy()

        self.toolbar = FloatingToolbar(self)

    def show_main(self):
        self.root.deiconify()
        self.root.lift()

    # ========================================================
    # PICK + CREATE ACTION
    # ========================================================
    def prepare_picker(self):
        self.clear_markers()

        if self.toolbar:
            self.toolbar.win.withdraw()

        self.root.withdraw()

    def restore_after_picker(self):
        self.root.deiconify()

        if self.toolbar:
            self.toolbar.win.deiconify()

    def pick_single_action(self, open_toolbar_after=False):
        self.prepare_picker()

        def position_selected(pos):
            self.restore_after_picker()

            if not pos:
                self.draw_markers()
                return

            action = {
                "type": "click",
                "x": pos["x"],
                "y": pos["y"],
                "button": "left",
                "clicks": 1,
                "delay": 0.5,
                "start_cycle": 1,
                "end_cycle": 0
            }

            def saved(updated):
                self.single_action = updated
                self.refresh_main_info()

                if open_toolbar_after:
                    self.create_toolbar()
                    self.root.withdraw()

                self.draw_markers()

            ClickSettings(self.root, action, saved)

        TargetSelector(self, "point", position_selected)

    def add_click_from_toolbar(self):
        if self.mode.get() == "single":
            self.pick_single_action(open_toolbar_after=False)
            return

        self.prepare_picker()

        def position_selected(pos):
            self.restore_after_picker()

            if not pos:
                self.draw_markers()
                return

            action = {
                "type": "click",
                "x": pos["x"],
                "y": pos["y"],
                "button": "left",
                "clicks": 1,
                "delay": 0.5,
                "start_cycle": 1,
                "end_cycle": 0
            }

            ClickSettings(
                self.root,
                action,
                lambda updated: self.append_multi_action(updated)
            )

        TargetSelector(self, "point", position_selected)

    def add_scroll_from_toolbar(self):
        self.prepare_picker()

        def position_selected(pos):
            self.restore_after_picker()

            if not pos:
                self.draw_markers()
                return

            action = {
                "type": "scroll",
                "x": pos["x"],
                "y": pos["y"],
                "amount": -5,
                "delay": 0.5,
                "start_cycle": 1,
                "end_cycle": 0
            }

            ScrollSettings(
                self.root,
                action,
                lambda updated: self.append_multi_action(updated)
            )

        TargetSelector(self, "point", position_selected)

    def add_swipe_from_toolbar(self):
        self.prepare_picker()

        def position_selected(pos):
            self.restore_after_picker()

            if not pos:
                self.draw_markers()
                return

            action = {
                "type": "swipe",
                "x1": pos["x1"],
                "y1": pos["y1"],
                "x2": pos["x2"],
                "y2": pos["y2"],
                "duration": 0.5,
                "delay": 0.5,
                "start_cycle": 1,
                "end_cycle": 0
            }

            SwipeSettings(
                self.root,
                action,
                lambda updated: self.append_multi_action(updated)
            )

        TargetSelector(self, "swipe", position_selected)

    def append_multi_action(self, action):
        normalize_cycle_rule(action)
        self.actions.append(action)
        self.draw_markers()
        self.refresh_main_info()

    # ========================================================
    # MODE SETTINGS
    # ========================================================
    def open_mode_settings(self, mode):
        if self.running:
            return

        self.mode.set(mode)

        win = tk.Toplevel(self.root)
        win.title(
            "Single Target Settings"
            if mode == "single"
            else "Multi Target Settings"
        )
        win.geometry("520x650")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        body = tk.Frame(win, bg=BG_CARD, padx=20, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text=(
                "SINGLE TARGET SETTINGS"
                if mode == "single"
                else "MULTI TARGET SETTINGS"
            ),
            font=("Georgia", 15, "bold")
        ).pack(anchor="w")

        tk.Label(
            body,
            text="Yahan current setup ki saari important information dikhegi.",
            fg=TEXT_SOFT
        ).pack(anchor="w", pady=(3, 16))

        # Run info section
        info_box = tk.Frame(
            body,
            bg=BG_PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0
        )
        info_box.pack(fill="x", pady=(0, 14))

        self.settings_info = tk.Label(
            info_box,
            bg=BG_PANEL,
            fg=TEXT,
            justify="left",
            anchor="w",
            padx=12,
            pady=10,
            font=("Georgia", 9)
        )
        self.settings_info.pack(fill="x")

        def update_info():
            if self.loop_mode.get() == "cycles":
                stop = f"{self.cycles.get()} cycles"
            elif self.loop_mode.get() == "time":
                stop = f"{self.duration_seconds.get()} sec"
            else:
                stop = "Manual stop"

            if mode == "single":
                if self.single_action:
                    action_info = action_text(self.single_action)
                else:
                    action_info = "No target selected"
            else:
                action_info = f"{len(self.actions)} actions configured"

            self.settings_info.config(
                text=(
                    f"Current: {action_info}\n"
                    f"Stop condition: {stop}\n"
                    f"Cycle delay: {self.cycle_delay.get()} sec\n"
                    f"Shortcuts: Start {self.start_hotkey.get()} • "
                    f"Pause {self.pause_hotkey.get()} • Stop {self.stop_hotkey.get()}"
                )
            )

        update_info()

        # Run conditions
        tk.Label(
            body,
            text="STOP CONDITION",
            font=("Georgia", 10, "bold")
        ).pack(anchor="w", pady=(0, 5))

        tk.Radiobutton(
            body,
            text="Run indefinitely / manually stop",
            variable=self.loop_mode,
            value="infinite",
            command=lambda: (update_info(), self.refresh_main_info())
        ).pack(anchor="w")

        row1 = tk.Frame(body, bg=BG_CARD)
        row1.pack(fill="x", pady=3)

        tk.Radiobutton(
            row1,
            text="Stop after seconds:",
            variable=self.loop_mode,
            value="time",
            command=lambda: (update_info(), self.refresh_main_info())
        ).pack(side="left")

        tk.Entry(
            row1,
            textvariable=self.duration_seconds,
            width=10
        ).pack(side="left", padx=7)

        row2 = tk.Frame(body, bg=BG_CARD)
        row2.pack(fill="x", pady=3)

        tk.Radiobutton(
            row2,
            text="Stop after cycles:",
            variable=self.loop_mode,
            value="cycles",
            command=lambda: (update_info(), self.refresh_main_info())
        ).pack(side="left")

        tk.Entry(
            row2,
            textvariable=self.cycles,
            width=10
        ).pack(side="left", padx=7)

        row3 = tk.Frame(body, bg=BG_CARD)
        row3.pack(fill="x", pady=(8, 12))

        tk.Label(row3, text="Delay after full cycle:").pack(side="left")
        tk.Spinbox(
            row3,
            from_=0,
            to=3600,
            increment=0.1,
            textvariable=self.cycle_delay,
            width=10
        ).pack(side="left", padx=7)
        tk.Label(row3, text="sec").pack(side="left")

        if mode == "single":
            tk.Button(
                body,
                text="SELECT / CHANGE TARGET",
                bg=RED_BRIGHT,
                fg=TEXT,
                relief="flat",
                pady=8,
                command=lambda: (win.destroy(), self.pick_single_action(False))
            ).pack(fill="x", pady=(8, 5))

            tk.Button(
                body,
                text="EDIT CLICK SETTINGS",
                pady=8,
                command=lambda: self.edit_single_action(win)
            ).pack(fill="x")

        else:
            tk.Button(
                body,
                text=f"OPEN ACTION LIST ({len(self.actions)})",
                bg=RED_BRIGHT,
                fg=TEXT,
                relief="flat",
                pady=8,
                command=lambda: (win.destroy(), self.open_action_list())
            ).pack(fill="x", pady=(8, 5))

        tk.Button(
            body,
            text="SAVE CONFIGURATION",
            bg=RED_BRIGHT,
            fg=TEXT,
            relief="flat",
            pady=8,
            command=self.save_current_config
        ).pack(fill="x", pady=(18, 5))

        tk.Button(
            body,
            text="COMMON SETTINGS / SHORTCUTS",
            pady=8,
            command=self.open_common_settings
        ).pack(fill="x", pady=5)

        tk.Button(
            body,
            text="CLOSE",
            pady=8,
            command=lambda: (self.refresh_main_info(), win.destroy())
        ).pack(fill="x", pady=5)

    def edit_single_action(self, parent_window=None):
        if not self.single_action:
            messagebox.showinfo(APP_NAME, "Pehle target select karo.")
            return

        ClickSettings(
            self.root,
            self.single_action,
            lambda updated: self.save_single_edit(updated)
        )

    def save_single_edit(self, updated):
        self.single_action = updated
        self.draw_markers()
        self.refresh_main_info()

    # ========================================================
    # MULTI ACTION LIST
    # ========================================================
    def open_action_list(self):
        if self.running:
            return

        self.mode.set("multi")

        win = tk.Toplevel(self.root)
        win.title("Multi Target Actions")
        win.geometry("700x560")

        lb = tk.Listbox(
            win,
            font=("Georgia", 10)
        )
        lb.pack(fill="both", expand=True, padx=12, pady=12)

        def refresh():
            lb.delete(0, "end")

            if not self.actions:
                lb.insert("end", "No actions. + Click / Swipe / Scroll add karo.")
                return

            for i, action in enumerate(self.actions, 1):
                lb.insert(
                    "end",
                    f"{i}. {action_text(action)}"
                )

        def selected_index():
            selected = lb.curselection()
            if not selected:
                return None
            index = selected[0]
            if index >= len(self.actions):
                return None
            return index

        def add_click():
            win.destroy()
            if not self.toolbar:
                self.create_toolbar()
            self.add_click_from_toolbar()

        def add_swipe():
            win.destroy()
            if not self.toolbar:
                self.create_toolbar()
            self.add_swipe_from_toolbar()

        def add_scroll():
            win.destroy()
            if not self.toolbar:
                self.create_toolbar()
            self.add_scroll_from_toolbar()

        def edit():
            index = selected_index()
            if index is None:
                return

            action = self.actions[index]

            def saved(updated):
                self.actions[index] = updated
                refresh()
                self.draw_markers()

            if action["type"] == "click":
                ClickSettings(win, action, saved)
            elif action["type"] == "scroll":
                ScrollSettings(win, action, saved)
            elif action["type"] == "swipe":
                SwipeSettings(win, action, saved)

        def remove():
            index = selected_index()
            if index is None:
                return

            self.actions.pop(index)
            refresh()
            self.draw_markers()

        def move(direction):
            index = selected_index()
            if index is None:
                return

            new_index = index + direction

            if not 0 <= new_index < len(self.actions):
                return

            self.actions[index], self.actions[new_index] = (
                self.actions[new_index],
                self.actions[index]
            )

            refresh()
            lb.selection_set(new_index)

        btns = tk.Frame(win, bg=BG_CARD)
        btns.pack(fill="x", padx=12, pady=(0, 12))

        tk.Button(btns, text="+ Click", command=add_click).pack(side="left")
        tk.Button(btns, text="↪ Swipe", command=add_swipe).pack(side="left", padx=5)
        tk.Button(btns, text="↕ Scroll", command=add_scroll).pack(side="left")
        tk.Button(btns, text="Edit", command=edit).pack(side="left", padx=5)
        tk.Button(btns, text="Delete", command=remove).pack(side="left")
        tk.Button(btns, text="↑", command=lambda: move(-1), width=3).pack(side="left", padx=(10, 2))
        tk.Button(btns, text="↓", command=lambda: move(1), width=3).pack(side="left")

        tk.Button(btns, text="Close", command=win.destroy).pack(side="right")

        lb.bind("<Double-1>", lambda _e: edit())

        refresh()

    # ========================================================
    # COMMON SETTINGS / HOTKEYS
    # ========================================================
    def open_common_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Common Settings")
        win.geometry("500x520")
        win.resizable(False, False)
        win.transient(self.root)

        body = tk.Frame(win, bg=BG_CARD, padx=20, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="COMMON SETTINGS",
            font=("Georgia", 15, "bold")
        ).pack(anchor="w")

        tk.Label(
            body,
            text="Global shortcuts doosri application focus me ho tab bhi kaam karenge.",
            fg=TEXT_SOFT,
            wraplength=440,
            justify="left"
        ).pack(anchor="w", pady=(3, 16))

        values = [
            "F6", "F7", "F8", "F9", "F10", "F11", "F12",
            "Ctrl+Alt+S",
            "Ctrl+Alt+P",
            "Ctrl+Alt+X",
            "Ctrl+Shift+S",
            "Ctrl+Shift+P",
            "Ctrl+Shift+X"
        ]

        for title, variable in [
            ("START shortcut", self.start_hotkey),
            ("PAUSE / RESUME shortcut", self.pause_hotkey),
            ("STOP shortcut", self.stop_hotkey)
        ]:
            tk.Label(
                body,
                text=title,
                font=("Georgia", 9, "bold")
            ).pack(anchor="w", pady=(6, 3))

            ttk.Combobox(
                body,
                textvariable=variable,
                values=values,
                state="readonly"
            ).pack(fill="x")

        tk.Label(
            body,
            text=(
                "\nTarget Selection:\n"
                "• Position select hote waqt mouse CROSSHAIR banega.\n"
                "• Red laser crosshair + live X/Y coordinates dikhenge.\n"
                "• ESC se cancel.\n\n"
                "Safety:\n"
                "• Automation run hote hi target markers remove ho jate hain.\n"
                "• Mouse ko TOP-LEFT corner me le jaane se PyAutoGUI failsafe stop hota hai."
            ),
            justify="left",
            fg=TEXT_SOFT,
            wraplength=440
        ).pack(anchor="w", pady=(10, 14))

        tk.Button(
            body,
            text="APPLY SHORTCUTS",
            bg=RED_BRIGHT,
            fg=TEXT,
            relief="flat",
            pady=9,
            command=lambda: self.register_hotkeys(show_message=True)
        ).pack(fill="x")

        tk.Button(
            body,
            text="CLOSE",
            pady=8,
            command=lambda: (self.refresh_main_info(), win.destroy())
        ).pack(fill="x", pady=(8, 0))

    def register_hotkeys(self, show_message=False):
        try:
            start = hotkey_to_pynput(self.start_hotkey.get())
            pause = hotkey_to_pynput(self.pause_hotkey.get())
            stop = hotkey_to_pynput(self.stop_hotkey.get())

            if len({start, pause, stop}) != 3:
                raise ValueError("Start, Pause aur Stop shortcuts alag honi chahiye.")

            if self.hotkey_listener:
                try:
                    self.hotkey_listener.stop()
                except Exception:
                    pass

            mapping = {
                start: lambda: self.event_queue.put(("start", None)),
                pause: lambda: self.event_queue.put(("pause", None)),
                stop: lambda: self.event_queue.put(("stop", None))
            }

            self.hotkey_listener = keyboard.GlobalHotKeys(mapping)
            self.hotkey_listener.daemon = True
            self.hotkey_listener.start()

            self.refresh_main_info()

            if show_message:
                messagebox.showinfo(
                    APP_NAME,
                    "Shortcuts applied successfully."
                )

        except Exception as exc:
            messagebox.showerror(
                APP_NAME,
                f"Shortcut apply nahi hua:\n{exc}"
            )

    # ========================================================
    # MARKERS
    # ========================================================
    def clear_markers(self):
        for marker in self.markers:
            marker.destroy()
        self.markers.clear()

    def draw_markers(self):
        self.clear_markers()

        if self.running:
            return

        if self.mode.get() == "single":
            if self.single_action:
                self.markers.append(
                    TargetMarker(
                        self.root,
                        self.single_action,
                        1
                    )
                )
            return

        number = 1

        for action in self.actions:
            self.markers.append(
                TargetMarker(
                    self.root,
                    action,
                    number
                )
            )

            if action["type"] == "swipe":
                # End point ko second simple marker dikhana.
                end_action = {
                    "type": "click",
                    "x": action["x2"],
                    "y": action["y2"],
                    "delay": 0,
                    "start_cycle": action.get("start_cycle", 1),
                    "end_cycle": action.get("end_cycle", 0)
                }
                self.markers.append(
                    TargetMarker(
                        self.root,
                        end_action,
                        number + 1
                    )
                )
                number += 2
            else:
                number += 1

    # ========================================================
    # AUTOMATION
    # ========================================================
    def snapshot_settings(self):
        try:
            seconds = max(1, int(self.duration_seconds.get()))
        except Exception:
            seconds = 300

        try:
            cycles = max(1, int(self.cycles.get()))
        except Exception:
            cycles = 10

        try:
            cycle_delay = max(0.0, float(self.cycle_delay.get()))
        except Exception:
            cycle_delay = 0.0

        if self.mode.get() == "single":
            actions = [normalize_cycle_rule(dict(self.single_action))] if self.single_action else []
        else:
            actions = [normalize_cycle_rule(dict(a)) for a in self.actions]

        return {
            "mode": self.mode.get(),
            "actions": actions,
            "loop_mode": self.loop_mode.get(),
            "seconds": seconds,
            "cycles": cycles,
            "cycle_delay": cycle_delay
        }

    def start_automation(self):
        if self.running:
            if self.paused:
                self.toggle_pause()
            return

        snapshot = self.snapshot_settings()

        if not snapshot["actions"]:
            messagebox.showwarning(APP_NAME, "Pehle target/action add karo.")
            return

        # IMPORTANT: marker completely remove before real clicks.
        self.clear_markers()

        self.running = True
        self.paused = False
        self.stop_event.clear()
        self.pause_event.set()

        if self.toolbar:
            self.toolbar.set_running(True)

        self.refresh_main_info()

        self.worker = threading.Thread(
            target=self.worker_loop,
            args=(snapshot,),
            daemon=True
        )
        self.worker.start()

    def stop_automation(self):
        if not self.running:
            return

        self.stop_event.set()
        self.pause_event.set()

    def toggle_pause(self):
        if not self.running:
            return

        if self.paused:
            self.paused = False
            self.pause_event.set()
        else:
            self.paused = True
            self.pause_event.clear()

        self.refresh_main_info()

    def wait_if_paused(self):
        while not self.pause_event.is_set():
            if self.stop_event.is_set():
                return False
            time.sleep(0.03)

        return not self.stop_event.is_set()

    def interruptible_sleep(self, seconds):
        end = time.monotonic() + max(0.0, float(seconds))

        while time.monotonic() < end:
            if self.stop_event.is_set():
                return False

            if not self.wait_if_paused():
                return False

            remaining = end - time.monotonic()

            if remaining <= 0:
                break

            time.sleep(min(0.03, remaining))

        return True

    def execute_action(self, action):
        kind = action["type"]

        if kind == "click":
            x = int(action["x"])
            y = int(action["y"])

            pyautogui.moveTo(x, y, duration=0.04)
            pyautogui.click(
                x=x,
                y=y,
                clicks=max(1, int(action.get("clicks", 1))),
                interval=0.08,
                button=action.get("button", "left")
            )

        elif kind == "scroll":
            x = int(action["x"])
            y = int(action["y"])

            pyautogui.moveTo(x, y, duration=0.04)
            pyautogui.scroll(
                int(action.get("amount", -5)),
                x=x,
                y=y
            )

        elif kind == "swipe":
            pyautogui.moveTo(
                int(action["x1"]),
                int(action["y1"]),
                duration=0.05
            )

            pyautogui.dragTo(
                int(action["x2"]),
                int(action["y2"]),
                duration=max(0.1, float(action.get("duration", 0.5))),
                button="left"
            )

    def worker_loop(self, snapshot):
        started = time.monotonic()
        completed_cycles = 0
        error_text = None

        try:
            while not self.stop_event.is_set():

                if snapshot["loop_mode"] == "time":
                    if time.monotonic() - started >= snapshot["seconds"]:
                        break

                if snapshot["loop_mode"] == "cycles":
                    if completed_cycles >= snapshot["cycles"]:
                        break

                cycle_number = completed_cycles + 1
                executed_any = False

                for action in snapshot["actions"]:
                    if self.stop_event.is_set():
                        break

                    if not self.wait_if_paused():
                        break

                    # Per-action cycle rule:
                    # end_cycle=1 => action sirf first complete run me chalega.
                    # cycle 2 se automatically SKIP hoga, delete karne ki need nahi.
                    if not action_active_for_cycle(action, cycle_number):
                        continue

                    self.execute_action(action)
                    executed_any = True

                    delay = max(0.0, float(action.get("delay", 0.0)))
                    if delay > 0:
                        if not self.interruptible_sleep(delay):
                            break

                completed_cycles += 1

                if self.stop_event.is_set():
                    break

                if snapshot["cycle_delay"] > 0:
                    if not self.interruptible_sleep(snapshot["cycle_delay"]):
                        break
                elif not executed_any:
                    # Prevent a tight CPU loop when current cycle has no active action.
                    if not self.interruptible_sleep(0.03):
                        break

        except pyautogui.FailSafeException:
            error_text = "Emergency stop hua: mouse TOP-LEFT corner par gaya."

        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"

        finally:
            self.event_queue.put(("worker_done", error_text))

    def worker_finished(self, error_text):
        self.running = False
        self.paused = False
        self.stop_event.clear()
        self.pause_event.set()

        if self.toolbar:
            self.toolbar.set_running(False)

        self.refresh_main_info()
        self.draw_markers()

        if error_text:
            messagebox.showerror(
                APP_NAME,
                f"Automation stopped:\n\n{error_text}"
            )

    # ========================================================
    # CONFIG SAVE / LOAD
    # ========================================================
    def current_config(self):
        return {
            "name": "Config",
            "mode": self.mode.get(),
            "single_action": self.single_action,
            "actions": self.actions,
            "loop_mode": self.loop_mode.get(),
            "duration_seconds": int(self.duration_seconds.get()),
            "cycles": int(self.cycles.get()),
            "cycle_delay": float(self.cycle_delay.get()),
            "start_hotkey": self.start_hotkey.get(),
            "pause_hotkey": self.pause_hotkey.get(),
            "stop_hotkey": self.stop_hotkey.get()
        }

    def apply_config(self, cfg):
        self.stop_automation()

        self.mode.set(cfg.get("mode", "single"))

        # New format
        self.single_action = cfg.get("single_action")

        # Compatibility with older V3 config
        if self.single_action is None and cfg.get("single_target"):
            old = cfg.get("single_target")
            if old:
                self.single_action = {
                    "type": "click",
                    "x": old["x"],
                    "y": old["y"],
                    "button": cfg.get("click_button", "left"),
                    "clicks": 2 if cfg.get("double_click", False) else 1,
                    "delay": cfg.get("click_interval", 1.0),
                    "start_cycle": 1,
                    "end_cycle": 0
                }

        self.actions = cfg.get("actions", [])

        if self.single_action:
            normalize_cycle_rule(self.single_action)

        # Old actions may not have per-action settings / cycle rules
        for action in self.actions:
            normalize_cycle_rule(action)
            action.setdefault("delay", cfg.get("click_interval", 1.0))

            if action.get("type") == "click":
                action.setdefault("button", cfg.get("click_button", "left"))
                action.setdefault(
                    "clicks",
                    2 if cfg.get("double_click", False) else 1
                )

            if action.get("type") == "swipe":
                action.setdefault("duration", 0.5)

        self.loop_mode.set(
            cfg.get(
                "loop_mode",
                cfg.get("stop_mode", "infinite")
            )
        )

        self.duration_seconds.set(
            cfg.get(
                "duration_seconds",
                cfg.get("run_seconds", 300)
            )
        )

        self.cycles.set(
            cfg.get(
                "cycles",
                cfg.get("run_cycles", 10)
            )
        )

        self.cycle_delay.set(cfg.get("cycle_delay", 0.0))

        self.start_hotkey.set(cfg.get("start_hotkey", "F7"))
        self.pause_hotkey.set(cfg.get("pause_hotkey", "F9"))
        self.stop_hotkey.set(cfg.get("stop_hotkey", "F8"))

        self.register_hotkeys(show_message=False)
        self.draw_markers()
        self.refresh_main_info()

    def _read_registry_configs(self):
        if os.name != "nt" or winreg is None:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_READ) as key:
                raw, _value_type = winreg.QueryValueEx(key, REGISTRY_VALUE)
            data = json.loads(raw) if raw else []
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return None
        except Exception:
            return []

    def _write_registry_configs(self, configs):
        if os.name != "nt" or winreg is None:
            return False
        try:
            raw = json.dumps(configs, ensure_ascii=False, separators=(",", ":"))
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                REGISTRY_PATH,
                0,
                winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, REGISTRY_VALUE, 0, winreg.REG_SZ, raw)
            return True
        except Exception:
            return False

    def _migrate_legacy_json_once(self):
        """Import old saved_configs.json once, then remove it from app folder."""
        if not os.path.exists(LEGACY_CONFIG_FILE):
            return None
        try:
            with open(LEGACY_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []

            if self._write_registry_configs(data):
                try:
                    os.remove(LEGACY_CONFIG_FILE)
                except Exception:
                    pass
                return data
            return data
        except Exception:
            return None

    def read_saved_configs(self):
        # Windows EXE: configs live in HKCU\Software\AutoClick, so no
        # saved_configs.json is created beside the program.
        data = self._read_registry_configs()
        if data is not None:
            return data

        # First run after upgrading: migrate the old JSON automatically.
        migrated = self._migrate_legacy_json_once()
        if migrated is not None:
            return migrated

        # Non-Windows fallback only.
        try:
            if os.path.exists(FALLBACK_CONFIG_FILE):
                with open(FALLBACK_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            pass
        return []

    def write_saved_configs(self, configs):
        if self._write_registry_configs(configs):
            # Remove any old visible JSON after a successful internal save.
            try:
                if os.path.exists(LEGACY_CONFIG_FILE):
                    os.remove(LEGACY_CONFIG_FILE)
            except Exception:
                pass
            return

        # Non-Windows fallback; never writes saved_configs.json beside the app.
        with open(FALLBACK_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)

    def save_current_config(self):
        name = simpledialog.askstring(
            "Save Configuration",
            "Configuration name:"
        )

        if not name:
            return

        cfg = self.current_config()
        cfg["name"] = name.strip()

        configs = self.read_saved_configs()

        replaced = False

        for i, old in enumerate(configs):
            if old.get("name", "").lower() == cfg["name"].lower():
                configs[i] = cfg
                replaced = True
                break

        if not replaced:
            configs.append(cfg)

        self.write_saved_configs(configs)

        messagebox.showinfo(
            APP_NAME,
            f'"{cfg["name"]}" save ho gaya.'
        )

    def manage_configs(self):
        win = tk.Toplevel(self.root)
        win.title("Manage Configurations")
        win.geometry("540x480")

        lb = tk.Listbox(
            win,
            font=("Georgia", 10)
        )
        lb.pack(fill="both", expand=True, padx=12, pady=12)

        def refresh():
            lb.delete(0, "end")

            configs = self.read_saved_configs()

            for cfg in configs:
                mode = (
                    "Single"
                    if cfg.get("mode", "single") == "single"
                    else "Multi"
                )

                action_count = (
                    1
                    if mode == "Single" and (
                        cfg.get("single_action")
                        or cfg.get("single_target")
                    )
                    else len(cfg.get("actions", []))
                )

                lb.insert(
                    "end",
                    f"{cfg.get('name', 'Config')}   [{mode}]   •   {action_count} action(s)"
                )

        def load():
            selected = lb.curselection()

            if not selected:
                return

            configs = self.read_saved_configs()
            self.apply_config(configs[selected[0]])
            win.destroy()

        def delete():
            selected = lb.curselection()

            if not selected:
                return

            configs = self.read_saved_configs()
            configs.pop(selected[0])
            self.write_saved_configs(configs)
            refresh()

        btns = tk.Frame(win, bg=BG_CARD)
        btns.pack(fill="x", padx=12, pady=(0, 12))

        tk.Button(
            btns,
            text="LOAD",
            bg=RED_BRIGHT,
            fg=TEXT,
            relief="flat",
            padx=18,
            pady=7,
            command=load
        ).pack(side="left")

        tk.Button(
            btns,
            text="DELETE",
            padx=14,
            pady=7,
            command=delete
        ).pack(side="left", padx=8)

        tk.Button(
            btns,
            text="CLOSE",
            padx=14,
            pady=7,
            command=win.destroy
        ).pack(side="right")

        lb.bind("<Double-1>", lambda _e: load())

        refresh()

    def export_script(self):
        path = filedialog.asksaveasfilename(
            title="Export Auto Clicker Script",
            defaultextension=".json",
            filetypes=[("JSON Script", "*.json")]
        )

        if not path:
            return

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.current_config(), f, indent=2)

        messagebox.showinfo(APP_NAME, "Script export ho gaya.")

    def import_script(self):
        path = filedialog.askopenfilename(
            title="Import Auto Clicker Script",
            filetypes=[("JSON Script", "*.json")]
        )

        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            self.apply_config(cfg)
            messagebox.showinfo(APP_NAME, "Script import ho gaya.")

        except Exception as exc:
            messagebox.showerror(
                APP_NAME,
                f"Import failed:\n{exc}"
            )

    # ========================================================
    # INSTRUCTIONS
    # ========================================================
    def show_instructions(self, mode):
        if mode == "single":
            text = (
                "SINGLE TARGET MODE\n\n"
                "1. ENABLE dabao.\n"
                "2. Mouse CROSSHAIR ban jayega.\n"
                "3. Jahan click chahiye wahan LEFT CLICK karo.\n"
                "4. Click Settings me button, click count aur delay set karo.\n"
                "5. Floating toolbar me ▶ se start.\n"
                "6. F8 se kisi bhi time STOP.\n\n"
                "Target marker automation chalne ke waqt remove ho jata hai, "
                "isliye actual screen/button par click hota hai."
            )
        else:
            text = (
                "MULTI TARGET MODE\n\n"
                "▶  Start / Stop\n"
                "+  Click point\n"
                "↪  Swipe\n"
                "↕  Scroll\n"
                "−  Last action remove\n"
                "⚙  Main settings\n"
                "✥  Toolbar move\n\n"
                "Har action ke baad uska apna delay set kar sakte ho.\n"
                "Har action me Start cycle + Remove after cycle bhi set kar sakte ho.\n"
                "Example: Window Close click me Remove after cycle = 1 rakho; cycle 2 se wo skip hoga.\n"
                "Example: Click 1 → 2 sec → Click 2 → 0.5 sec → Scroll → 1 sec."
            )

        messagebox.showinfo(
            "Instructions",
            text
        )

    # ========================================================
    # EVENT QUEUE
    # ========================================================
    def process_events(self):
        try:
            while True:
                name, payload = self.event_queue.get_nowait()

                if name == "start":
                    self.start_automation()

                elif name == "pause":
                    self.toggle_pause()

                elif name == "stop":
                    self.stop_automation()

                elif name == "worker_done":
                    self.worker_finished(payload)

        except queue.Empty:
            pass

        self.root.after(80, self.process_events)

    # ========================================================
    # EXIT
    # ========================================================
    def exit_app(self):
        self.stop_event.set()
        self.pause_event.set()

        self.clear_markers()

        if self.toolbar:
            self.toolbar.destroy()

        if self.hotkey_listener:
            try:
                self.hotkey_listener.stop()
            except Exception:
                pass

        if self.bg_animation:
            self.bg_animation.stop()
        if self.hero_animation:
            self.hero_animation.stop()
        if self.side_animation:
            self.side_animation.stop()
        if hasattr(self, "canvas_bg_animation") and self.canvas_bg_animation:
            self.canvas_bg_animation.stop()
        if hasattr(self, "canvas_side_animation") and self.canvas_side_animation:
            self.canvas_side_animation.stop()

        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AutoClickerApp().run()
