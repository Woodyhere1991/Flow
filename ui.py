"""
Small set of dark, rounded widgets used by the dictation app.

Stock ttk cannot be styled into anything modern on Windows, so anything with a
custom shape (cards, switches, segmented controls, key caps) is drawn on a
Canvas instead.
"""

import ctypes
import tkinter as tk
from ctypes import wintypes


def enable_dpi_awareness():
    """Render crisply on scaled displays.

    Without this Windows renders the window at 96 DPI and bitmap-stretches it,
    which makes every line and glyph soft. Must run before the Tk root exists.
    """
    # Each call's RETURN VALUE must be checked - they fail by returning
    # false/non-zero rather than raising, and returning early on a failed call
    # silently leaves the process DPI-virtualised (i.e. blurry).
    try:                                    # per-monitor v2, best fidelity
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(-4):
            return "per-monitor-v2"
    except Exception:
        pass
    try:                                    # Windows 8.1+, S_OK == 0
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except Exception:
        pass
    try:                                    # last resort, system-DPI only
        if ctypes.windll.user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return "none"


SCALE = 1.0


def scale_for_dpi(root):
    """Match Tk's internal scaling to the monitor, and return the factor.

    Tk's own scaling only affects fonts, so the widgets below multiply their
    hard-coded pixel sizes by SCALE to stay in proportion.
    """
    global SCALE
    try:
        dpi = root.winfo_fpixels("1i")
    except Exception:
        dpi = 96.0
    SCALE = dpi / 96.0
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass
    return SCALE


def s(value):
    """Scale a pixel measurement for the current display."""
    return int(round(value * SCALE))


def dark_titlebar(root):
    """Ask DWM for the dark title bar so the frame matches the window."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        flag = ctypes.c_int(1)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE on current Windows 10/11; older
        # builds used 19, so try both and ignore failures.
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(flag), ctypes.sizeof(flag)) == 0:
                break
    except Exception:
        pass


def set_window_icon(root, ico_path):
    """Give the title bar AND taskbar button a crisp icon.

    tkinter's iconbitmap() does not reliably pick a large-enough frame out of
    a multi-resolution .ico on a scaled display - it was showing a tiny frame
    stretched up, which looks blurry on the taskbar. Loading the icon
    explicitly at the exact size Windows asks for (GetSystemMetrics) and
    setting it via WM_SETICON fixes that.
    """
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        u = ctypes.windll.user32

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x10
        SM_CXICON, SM_CYICON = 11, 12
        SM_CXSMICON, SM_CYSMICON = 49, 50
        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1

        u.LoadImageW.restype = wintypes.HICON
        u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SendMessageW.restype = wintypes.LPARAM
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]

        big_px = u.GetSystemMetrics(SM_CXICON)
        small_px = u.GetSystemMetrics(SM_CXSMICON)
        path = str(ico_path)

        big = u.LoadImageW(None, path, IMAGE_ICON, big_px, big_px, LR_LOADFROMFILE)
        if big:
            u.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        small = u.LoadImageW(None, path, IMAGE_ICON, small_px, small_px, LR_LOADFROMFILE)
        if small:
            u.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
    except Exception:
        pass


def fit_to_screen(root, width, height, margin=80):
    """Clamp a desired window size to what actually fits on this monitor."""
    root.update_idletasks()
    max_w = root.winfo_screenwidth() - s(20)
    max_h = root.winfo_screenheight() - s(margin)
    return min(width, max_w), min(height, max_h)


# palette -------------------------------------------------------------------
BG = "#0b0b0f"
CARD = "#17171c"
CARD_HI = "#1f1f26"
LINE = "#2a2a33"
TEXT = "#f4f4f6"
MUTED = "#8b8b96"
ACCENT = "#7c5cff"
ACCENT_2 = "#38bdf8"
GOOD = "#32d74b"
WARN = "#ffd60a"
REC = "#ff453a"

FONT = "Segoe UI"


def round_rect(canvas, x0, y0, x1, y1, r, **kw):
    """Rounded rectangle as a smoothed polygon."""
    r = min(r, abs(x1 - x0) / 2, abs(y1 - y0) / 2)
    pts = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Card(tk.Canvas):
    """A rounded panel you can pack normal widgets into via .body.

    Height follows the content unless one is given explicitly - fixed heights
    silently clip trailing labels when fonts scale on a high-DPI display.
    """

    def __init__(self, parent, height=None, autosize=True, **kw):
        super().__init__(parent, bg=BG, highlightthickness=0, bd=0,
                         height=height or 10, **kw)
        self.body = tk.Frame(self, bg=CARD)
        self._win = self.create_window(0, 0, window=self.body, anchor="nw")
        self._autosize = autosize and height is None
        self.bind("<Configure>", self._redraw)
        if self._autosize:
            self.body.bind("<Configure>", self._fit)

    def _fit(self, _event=None):
        want = self.body.winfo_reqheight() + 2
        if want > 12 and abs(want - int(self["height"])) > 1:
            self.configure(height=want)

    def _redraw(self, event):
        self.delete("bg")
        round_rect(self, 0, 0, event.width - 1, event.height - 1, 14,
                   fill=CARD, outline=LINE, tags="bg")
        self.tag_lower("bg")
        self.coords(self._win, 1, 1)
        self.itemconfig(self._win, width=event.width - 2, height=event.height - 2)


class Toggle(tk.Canvas):
    """iOS-style switch bound to a tk.BooleanVar."""

    def __init__(self, parent, variable, command=None):
        self.W, self.H = s(44), s(24)
        super().__init__(parent, width=self.W, height=self.H, bg=CARD,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.var = variable
        self.command = command
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _click(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        track = ACCENT if on else "#3a3a44"
        round_rect(self, 1, 1, self.W - 1, self.H - 1, (self.H - 2) / 2,
                   fill=track, outline=track)
        r = (self.H - s(8)) / 2
        cx = (self.W - r - s(5)) if on else (r + s(5))
        cy = self.H / 2
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#ffffff",
                         outline="#ffffff")


class Segmented(tk.Canvas):
    """Two-or-more option selector bound to a tk.StringVar."""

    def __init__(self, parent, options, variable, width=300, height=34,
                 command=None, labels=None):
        width, height = s(width), s(height)
        super().__init__(parent, width=width, height=height, bg=CARD,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.options = list(options)
        self.var = variable
        self.command = command
        self.labels = labels or {}
        self._cw, self._ch = width, height
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _click(self, event):
        idx = int(event.x // (self._cw / len(self.options)))
        idx = max(0, min(idx, len(self.options) - 1))
        self.var.set(self.options[idx])
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        round_rect(self, 0, 0, self._cw - 1, self._ch - 1, 9,
                   fill="#101014", outline=LINE)
        seg = self._cw / len(self.options)
        for i, opt in enumerate(self.options):
            x0 = i * seg
            active = self.var.get() == opt
            if active:
                round_rect(self, x0 + 3, 3, x0 + seg - 3, self._ch - 3, 7,
                           fill=ACCENT, outline=ACCENT)
            label = self.labels.get(opt, opt.title())
            self.create_text(x0 + seg / 2, self._ch / 2,
                             text=label, fill=TEXT if active else MUTED,
                             font=(FONT, 9, "bold" if active else "normal"))


class KeyCaps(tk.Canvas):
    """Renders a shortcut as little keyboard caps, e.g.  Ctrl + Win."""

    def __init__(self, parent, keys, bg=CARD, height=38):
        self.keys = keys
        self._bg = bg
        super().__init__(parent, height=s(height), bg=bg,
                         highlightthickness=0, bd=0)
        self.bind("<Configure>", lambda _e: self._draw())

    def _draw(self):
        self.delete("all")
        x = s(2)
        h = s(28)
        y = (int(self["height"]) - h) / 2
        for i, key in enumerate(self.keys):
            w = s(22) + len(key) * s(9)
            round_rect(self, x, y, x + w, y + h, 7,
                       fill=CARD_HI, outline=LINE)
            self.create_text(x + w / 2, y + h / 2, text=key, fill=TEXT,
                             font=(FONT, 10, "bold"))
            x += w
            if i < len(self.keys) - 1:
                self.create_text(x + s(9), y + h / 2, text="+", fill=MUTED,
                                 font=(FONT, 10))
                x += s(20)


class Wave(tk.Canvas):
    """Live level history, drawn as centred bars."""

    def __init__(self, parent, width=300, height=52, bars=34, bg=CARD):
        width, height = s(width), s(height)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.bars = bars
        self.levels = [0.0] * bars
        self._cw, self._ch = width, height
        self.active = False
        self.bind("<Configure>", self._on_resize)
        self.draw()

    def _on_resize(self, event):
        self._cw, self._ch = event.width, event.height
        self.draw()

    def push(self, level):
        self.levels.append(level)
        if len(self.levels) > self.bars:
            self.levels = self.levels[-self.bars:]

    def reset(self):
        self.levels = [0.0] * self.bars

    def draw(self):
        import math
        self.delete("all")
        n = self.bars
        gap = 3
        bw = max(2, (self._cw - gap * (n - 1)) / n)
        mid = self._ch / 2
        for i, lvl in enumerate(self.levels[-n:]):
            db = 20 * math.log10(max(lvl, 1e-6))
            frac = max(0.03, min(1.0, (db + 60) / 60))
            bh = max(2, frac * (self._ch - 10))
            x = i * (bw + gap)
            if self.active:
                # fade older samples toward the accent colour
                colour = ACCENT if frac > 0.3 else "#4b4b57"
            else:
                colour = "#2c2c35"
            self.create_rectangle(x, mid - bh / 2, x + bw, mid + bh / 2,
                                  fill=colour, outline=colour)


class Button(tk.Canvas):
    """Flat rounded button."""

    def __init__(self, parent, text, command, primary=False, width=110,
                 height=34, bg=CARD):
        width, height = s(width), s(height)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.command = text, command
        self.primary = primary
        self._cw, self._ch = width, height
        self._hover = False
        self.bind("<Button-1>", lambda _e: self.command())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._draw()

    def set_text(self, text):
        """Change the label without rebuilding the button."""
        self.text = text
        self._draw()

    def _enter(self, _e):
        self._hover = True
        self._draw()

    def _leave(self, _e):
        self._hover = False
        self._draw()

    def _draw(self):
        self.delete("all")
        if self.primary:
            fill = "#8f72ff" if self._hover else ACCENT
            fg = "#ffffff"
        else:
            fill = CARD_HI if self._hover else "#202027"
            fg = TEXT
        round_rect(self, 0, 0, self._cw - 1, self._ch - 1, 9,
                   fill=fill, outline=fill)
        self.create_text(self._cw / 2, self._ch / 2, text=self.text, fill=fg,
                         font=(FONT, 9, "bold"))
