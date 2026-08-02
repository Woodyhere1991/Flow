r"""
Floating status pill, always on top of every window.

The hard requirement is that it must NEVER take keyboard focus. Dictation
pastes into whatever window is focused, so an overlay that activated itself
when shown would steal focus and the text would land in the overlay's own
process instead of the user's app. WS_EX_NOACTIVATE is what prevents that.
"""

import ctypes
import math
import tkinter as tk
from ctypes import wintypes

import ui

user32 = ctypes.WinDLL("user32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4

GA_ROOT = 2
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL

# Deliberately small and wordless. This sits on top of whatever the user is
# typing into, so it shows only that it is listening - never how many words it
# wrote, which would cover the very text they are dictating.
BARS = 11
PILL_W = 84
PILL_H = 24

BG = "#17171c"
EDGE = "#33333d"

# The window itself is always a rectangle; painting it this colour and marking
# that colour transparent is what leaves only the pill shape visible. It must
# be a colour used nowhere else in the drawing.
TRANSPARENT = "#ff00ff"
FG = "#f4f4f6"
DIM = "#5a5a66"
ACCENT = "#7c5cff"
REC = "#ff453a"
OK = "#32d74b"
BUSY = "#ffd60a"


class Overlay:
    """A small always-on-top pill showing mic state. Never takes focus."""

    def __init__(self, root, on_cancel=None):
        self.root = root
        self.on_cancel = on_cancel
        self.levels = [0.0] * BARS
        self.state = "hidden"
        self._phase = 0
        self._drag = None
        self._hide_job = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)          # no title bar or border
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.96)   # sits over the user's work
        self.win.configure(bg=TRANSPARENT)
        self.win.attributes("-transparentcolor", TRANSPARENT)

        self.w = ui.s(PILL_W)
        self.h = ui.s(PILL_H)
        self.win.geometry(f"{self.w}x{self.h}")

        self.canvas = tk.Canvas(self.win, width=self.w, height=self.h,
                                bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        # Drag to reposition, same as Wispr Flow's bar.
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<Button-3>", lambda _e: self._cancel())

        self._place_default()
        self.win.update_idletasks()
        self._make_non_activating()
        # Map it once so Tk treats the window as realised, then hide it through
        # Win32 so every later show/hide goes via the non-activating path.
        user32.ShowWindow(self._hwnd, SW_HIDE)

    # ------------------------------------------------------------ win32 ----
    def _make_non_activating(self):
        """Stop the pill from ever becoming the foreground window."""
        # winfo_id() is the Tk child window; the style has to go on the real
        # top-level, which GetAncestor(GA_ROOT) resolves for us.
        hwnd = user32.GetAncestor(self.win.winfo_id(), GA_ROOT)
        if not hwnd:
            hwnd = self.win.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        self._hwnd = hwnd

    def _place_default(self):
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - self.w) // 2
        y = sh - self.h - ui.s(70)         # just above the taskbar, out of the way
        self.win.geometry(f"{self.w}x{self.h}+{x}+{y}")

    # ------------------------------------------------------------- drag ----
    def _drag_start(self, event):
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())

    def _drag_move(self, event):
        if not self._drag:
            return
        dx, dy = self._drag
        self.win.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _cancel(self):
        if self.on_cancel:
            self.on_cancel()

    # ------------------------------------------------------------ states ----
    def show_listening(self):
        self._cancel_hide()
        self.state = "listening"
        self.levels = [0.0] * BARS
        self._show()
        self._render()

    def show_transcribing(self):
        self._cancel_hide()
        self.state = "transcribing"
        self._show()
        self._render()

    def show_done(self, message=None, good=True):
        """Flash briefly and vanish.

        message is accepted but intentionally ignored - the pill sits over the
        text being dictated, so telling the user what was written would cover
        the very thing they just wrote.
        """
        self._cancel_hide()
        self.state = "done" if good else "warn"
        self._show()
        self._render()
        self._hide_job = self.root.after(650, self.hide)

    def hide(self):
        self._cancel_hide()
        self.state = "hidden"
        user32.ShowWindow(self._hwnd, SW_HIDE)

    def _cancel_hide(self):
        if self._hide_job:
            try:
                self.root.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _show(self):
        # Deliberately NOT using Tk's deiconify(): it activates the window,
        # which yanks focus off whatever the user is typing into. ShowWindow
        # with SW_SHOWNOACTIVATE displays it without ever making it foreground.
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    # ------------------------------------------------------------ render ----
    def push_level(self, level):
        """Feed the newest mic level (0..1) into the waveform."""
        self.levels.append(level)
        if len(self.levels) > BARS:
            self.levels = self.levels[-BARS:]

    def tick(self):
        self._phase += 1
        if self.state != "hidden":
            self._render()

    def _render(self):
        c = self.canvas
        c.delete("all")
        w, h = self.w, self.h

        # Everything outside the pill stays TRANSPARENT so the window's square
        # corners are invisible - only the rounded shape shows on screen.
        c.create_rectangle(0, 0, w, h, fill=TRANSPARENT, outline=TRANSPARENT)

        r = h / 2
        c.create_oval(0, 0, h - 1, h - 1, fill=BG, outline=EDGE)
        c.create_oval(w - h, 0, w - 1, h - 1, fill=BG, outline=EDGE)
        c.create_rectangle(r, 0, w - r, h - 1, fill=BG, outline=BG)
        c.create_line(r, 0, w - r, 0, fill=EDGE)
        c.create_line(r, h - 1, w - r, h - 1, fill=EDGE)

        pad = ui.s(11)
        if self.state == "listening":
            self._draw_wave(c, pad, w - pad, h, live=True)
        elif self.state == "transcribing":
            self._draw_wave(c, pad, w - pad, h, live=False)
        elif self.state in ("done", "warn"):
            # No wording - just a brief tint, then it disappears on its own.
            colour = OK if self.state == "done" else BUSY
            cx, cy, rr = w / 2, h / 2, ui.s(4)
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                          fill=colour, outline=colour)

    def _draw_wave(self, c, x0, x1, h, live):
        """Thin centred bars. When not live, they shimmer to show work happening."""
        n = BARS
        span = x1 - x0
        step = span / n
        bw = max(ui.s(2), step * 0.55)
        mid = h / 2
        for i in range(n):
            x = x0 + i * step
            if live:
                lvl = self.levels[-n:][i] if i < len(self.levels[-n:]) else 0.0
                # Log scale: linear amplitude is invisible at speech levels.
                db = 20 * math.log10(max(lvl, 1e-6))
                frac = max(0.10, min(1.0, (db + 60) / 60))
                colour = ACCENT if frac > 0.25 else DIM
            else:
                # travelling ripple while transcribing
                frac = 0.25 + 0.35 * (1 + math.sin((i - self._phase * 0.9) / 1.6)) / 2
                colour = ACCENT
            bh = max(ui.s(2), frac * (h - ui.s(12)))
            c.create_rectangle(x, mid - bh / 2, x + bw, mid + bh / 2,
                               fill=colour, outline=colour)
