r"""
Floating status pill. It can sit above every window, or drop behind them.

The hard requirement is that it must NEVER take keyboard focus. Dictation
pastes into whatever window is focused, so an overlay that activated itself
when shown would steal focus and the text would land in the overlay's own
process instead of the user's app. WS_EX_NOACTIVATE is what prevents that.

Click starts or stops dictation, drag moves it, right-click hides it (or
cancels an in-flight recording), and double-click lets other windows cover it.
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
HWND_NOTOPMOST = -2
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
user32.GetDoubleClickTime.restype = wintypes.UINT

# Deliberately small and wordless. This sits on top of whatever the user is
# typing into, so it shows only that it is listening - never how many words it
# wrote, which would cover the very text they are dictating.
BARS = 13
PILL_W = 92
PILL_H = 26

BG = "#171029"
BG_TOP = "#241640"      # the pill is lit from above, like a real object
EDGE = "#3B2870"
EDGE_TOP = "#5B3FA8"

# The window itself is always a rectangle; painting it this colour and marking
# that colour transparent is what leaves only the pill shape visible. It must
# be a colour used nowhere else in the drawing.
TRANSPARENT = "#ff00ff"
FG = "#f4eeff"
DIM = "#8878B0"
ACCENT = "#ff5ad8"
REC = "#ff5c74"
OK = "#4cefa6"
BUSY = "#ffc94a"


def _double_click_ms():
    """Wait just long enough to tell a click from a double-click."""
    try:
        return min(350, max(200, int(user32.GetDoubleClickTime())))
    except Exception:
        return 280


class Overlay:
    """A small pill showing mic state. Never takes focus."""

    def __init__(self, root, on_cancel=None, on_toggle=None,
                 on_hide=None):
        self.root = root
        self.on_cancel = on_cancel
        self.on_toggle = on_toggle
        self.on_hide = on_hide
        self.levels = [0.0] * BARS
        self.state = "hidden"
        self.idle_enabled = False
        self.topmost = True
        self.hovered = False
        self._phase = 0
        self._drag = None
        self._drag_start_xy = None
        self._drag_moved = False
        self._hide_job = None
        self._click_job = None

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

        # A click starts/stops dictation. Moving while held still drags the pill.
        self.canvas.configure(cursor="hand2")
        self.canvas.bind("<Enter>", self._mouse_enter)
        self.canvas.bind("<Leave>", self._mouse_leave)
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Button-3>", self._right_click)

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
    def _mouse_enter(self, _event=None):
        self.hovered = True
        self._render()

    def _mouse_leave(self, _event=None):
        self.hovered = False
        self._render()

    def _drag_start(self, event):
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())
        self._drag_start_xy = (event.x_root, event.y_root)
        self._drag_moved = False

    def _drag_move(self, event):
        if not self._drag:
            return
        if self._drag_start_xy:
            sx, sy = self._drag_start_xy
            if abs(event.x_root - sx) + abs(event.y_root - sy) >= ui.s(5):
                self._drag_moved = True
        dx, dy = self._drag
        if self._drag_moved:
            self.win.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _drag_end(self, _event=None):
        clicked = self._drag is not None and not self._drag_moved
        self._drag = None
        self._drag_start_xy = None
        self._drag_moved = False
        if not clicked:
            return
        if self._click_job is not None:
            # Second click arrived before the first one fired. This used to
            # toggle stay-on-top, but an accidental double-click while simply
            # trying to dictate silently dropped the pill behind other
            # windows - it happened twice in real use. A double-click now
            # behaves as one click; the Settings switch is the only way to
            # change topmost.
            self._cancel_pending_click()
            self._fire_click()
            return
        self._click_job = self.root.after(_double_click_ms(), self._fire_click)

    def _fire_click(self):
        self._click_job = None
        if self.on_toggle:
            self.on_toggle()

    def _cancel_pending_click(self):
        if self._click_job is not None:
            try:
                self.root.after_cancel(self._click_job)
            except Exception:
                pass
            self._click_job = None

    def _right_click(self, _event=None):
        self._cancel_pending_click()
        if self.state == "listening":
            self._cancel()
            return
        if self.on_hide:
            self.on_hide()

    def _cancel(self):
        if self.on_cancel:
            self.on_cancel()

    # ------------------------------------------------------------ states ----
    def set_idle_enabled(self, enabled):
        """Keep a clickable mic visible whenever Flow is otherwise idle."""
        self.idle_enabled = bool(enabled)
        if self.idle_enabled and self.state in ("hidden", "idle"):
            self.show_idle()
        elif not self.idle_enabled:
            self.hide()

    def set_topmost(self, enabled):
        """Pin above every window, or let ordinary windows cover the pill."""
        self.topmost = bool(enabled)
        try:
            self.win.attributes("-topmost", self.topmost)
        except Exception:
            pass
        if self.state != "hidden" and getattr(self, "_hwnd", None):
            self._apply_z_order()

    def show_idle(self):
        if not self.idle_enabled:
            self.hide()
            return
        self._cancel_hide()
        self.state = "idle"
        self.levels = [0.0] * BARS
        self._show()
        self._render()

    def return_to_idle(self):
        if self.idle_enabled:
            self.show_idle()
        else:
            self.hide()

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
        self._hide_job = self.root.after(650, self._finish_flash)

    def _finish_flash(self):
        self._hide_job = None
        self.return_to_idle()

    def hide(self):
        self._cancel_hide()
        self._cancel_pending_click()
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
        self._apply_z_order()

    def _apply_z_order(self):
        insert = HWND_TOPMOST if self.topmost else HWND_NOTOPMOST
        user32.SetWindowPos(self._hwnd, insert, 0, 0, 0, 0,
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
            # Windows stacks topmost windows by recency: any other app that
            # asks for the same privilege after us sits above the pill, and a
            # one-shot topmost at show time slowly loses. Re-asserting every
            # few seconds keeps it above everything without stealing focus
            # (SWP_NOACTIVATE), and only while the user has not deliberately
            # let other windows cover it.
            if self.topmost and self._phase % 40 == 0:
                self._apply_z_order()

    def _render(self):
        c = self.canvas
        c.delete("all")
        w, h = self.w, self.h

        # Everything outside the pill stays TRANSPARENT so the window's square
        # corners are invisible - only the rounded shape shows on screen.
        c.create_rectangle(0, 0, w, h, fill=TRANSPARENT, outline=TRANSPARENT)

        # A capsule with a top-lit body. Tk cannot anti-alias, so instead of
        # fighting the jaggies the shape is built from a stack of thin
        # horizontal bands that shade from BG_TOP down to BG - the eye reads
        # the shading, not the edge.
        r = h / 2
        c.create_oval(0, 0, h - 1, h - 1, fill=BG, outline=EDGE)
        c.create_oval(w - h, 0, w - 1, h - 1, fill=BG, outline=EDGE)
        c.create_rectangle(r, 0, w - r, h - 1, fill=BG, outline=BG)
        bands = 7
        for i in range(bands):
            t = i / (bands - 1)
            y0 = 1 + t * (h - 3) * 0.55
            c.create_rectangle(r, y0, w - r, y0 + (h - 3) * 0.55 / bands + 1,
                               fill=ui.lerp_hex(BG_TOP, BG, t), outline="")
        c.create_line(r, 0, w - r, 0, fill=EDGE_TOP)
        c.create_line(r, h - 1, w - r, h - 1, fill=EDGE)
        c.create_arc(0, 0, h - 1, h - 1, start=90, extent=80, style="arc",
                     outline=EDGE_TOP)
        c.create_arc(w - h, 0, w - 1, h - 1, start=10, extent=80, style="arc",
                     outline=EDGE_TOP)

        pad = ui.s(12)
        if self.state == "idle":
            self._draw_mic(c, w, h)
        elif self.state == "listening":
            self._draw_wave(c, pad, w - pad, h, live=True)
        elif self.state == "transcribing":
            self._draw_wave(c, pad, w - pad, h, live=False)
        elif self.state in ("done", "warn"):
            # No wording - just a brief tint, then it disappears on its own.
            colour = OK if self.state == "done" else BUSY
            cx, cy = w / 2, h / 2
            for rr, blend in ((ui.s(8), 0.22), (ui.s(6), 0.5), (ui.s(4), 1.0)):
                fill = colour if blend == 1.0 else ui.lerp_hex(BG, colour, blend)
                c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                              fill=fill, outline="")

    def _draw_mic(self, c, w, h):
        """Small microphone affordance; lights up when it is ready to click."""
        colour = ACCENT if self.hovered else DIM
        cx = w / 2
        top = ui.s(6)
        bottom = h - ui.s(9)
        half = ui.s(3)
        if self.hovered:
            # A faint bloom so hovering feels like the mic is powering on.
            c.create_oval(cx - ui.s(9), h / 2 - ui.s(9),
                          cx + ui.s(9), h / 2 + ui.s(9),
                          fill=ui.lerp_hex(BG, colour, 0.20), outline="")
        c.create_oval(cx - half, top, cx + half, bottom,
                      fill=colour, outline=colour)
        c.create_oval(cx - half + ui.s(1), top + ui.s(1),
                      cx + half - ui.s(1), top + ui.s(4),
                      fill=ui.lerp_hex(colour, "#ffffff", 0.45), outline="")
        c.create_arc(cx - ui.s(6), top + ui.s(3), cx + ui.s(6),
                     h - ui.s(5), start=180, extent=180,
                     style="arc", outline=colour, width=max(1, ui.s(1.4)))
        c.create_line(cx, h - ui.s(7), cx, ui.s(0) + h - ui.s(4),
                      fill=colour, width=max(1, ui.s(1.4)))
        c.create_line(cx - ui.s(4), h - ui.s(4), cx + ui.s(4),
                      h - ui.s(4), fill=colour, width=max(1, ui.s(1.4)),
                      capstyle="round")

    def _draw_wave(self, c, x0, x1, h, live):
        """Centred bars with rounded caps and a soft bloom behind each one."""
        n = BARS
        span = x1 - x0
        step = span / n
        bw = max(ui.s(2), step * 0.5)
        mid = h / 2
        for i in range(n):
            x = x0 + i * step + bw / 2
            if live:
                lvl = self.levels[-n:][i] if i < len(self.levels[-n:]) else 0.0
                # Log scale: linear amplitude is invisible at speech levels.
                db = 20 * math.log10(max(lvl, 1e-6))
                frac = max(0.10, min(1.0, (db + 60) / 60))
                colour = ui.ribbon(ui.now_hue((i / n) * 0.5, 0.045))
            else:
                # travelling ripple while transcribing
                frac = 0.25 + 0.35 * (1 + math.sin((i - self._phase * 0.9) / 1.6)) / 2
                colour = ui.ribbon(ui.now_hue(self._phase * 0.008, 0.05))
            bh = max(ui.s(2), frac * (h - ui.s(13)))
            c.create_line(x, mid - bh / 2, x, mid + bh / 2,
                          fill=ui.lerp_hex(BG, colour, 0.30),
                          width=bw + ui.s(2), capstyle="round")
            c.create_line(x, mid - bh / 2, x, mid + bh / 2,
                          fill=ui.lerp_hex(colour, "#ffffff",
                                           0.08 + 0.22 * frac),
                          width=bw, capstyle="round")
