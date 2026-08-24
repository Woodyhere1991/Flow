"""
Small set of dark, rounded widgets used by the dictation app.

Stock ttk cannot be styled into anything modern on Windows, so anything with a
custom shape (cards, switches, segmented controls, key caps) is drawn on a
Canvas instead.
"""

import colorsys
import ctypes
import time as _clock
import tkinter as tk
import tkinter.font as tkfont
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


class Tooltip:
    """Show a short plain-language description for any Tk widget."""

    def __init__(self, widget, text, delay=350):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.pending = None
        self.window = None
        widget._flow_tooltip = self
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<FocusIn>", self._schedule, add="+")
        widget.bind("<FocusOut>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self.pending = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self.pending is not None:
            try:
                self.widget.after_cancel(self.pending)
            except Exception:
                pass
            self.pending = None

    def _show(self):
        self.pending = None
        if self.window or not self.text:
            return
        try:
            pointer_x = self.widget.winfo_pointerx()
            pointer_y = self.widget.winfo_pointery()
            x = pointer_x + s(14)
            y = pointer_y + s(18)
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            tk.Label(
                tip, text=self.text, bg=CARD, fg=TEXT,
                font=(FONT, 9), justify="left", wraplength=s(300),
                padx=s(10), pady=s(7), relief="solid", bd=1,
            ).pack()
            tip.update_idletasks()
            tip_w, tip_h = tip.winfo_reqwidth(), tip.winfo_reqheight()
            max_x = self.widget.winfo_screenwidth() - tip_w - s(8)
            max_y = self.widget.winfo_screenheight() - tip_h - s(8)
            x = max(s(8), min(x, max_x))
            if y > max_y:
                y = max(s(8), pointer_y - tip_h - s(12))
            tip.wm_geometry(f"+{x}+{y}")
            self.window = tip
        except Exception:
            self.window = None

    def _hide(self, _event=None):
        self._cancel()
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None


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


def place_centered(win, width, height):
    """Size a window and drop it in the middle of the screen."""
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


# palette -------------------------------------------------------------------
BG = "#0c0618"
CARD = "#181028"
CARD_HI = "#241638"
LINE = "#3b2566"
TEXT = "#f8f2ff"
MUTED = "#a08cc0"
ACCENT = "#ff4fd8"
ACCENT_2 = "#00e5ff"
GOOD = "#39ff88"
WARN = "#ffd60a"
REC = "#ff3860"
GRAD_B = "#8a5cff"

FONT = "Comic Sans MS"


def hsv_hex(h, sat=0.85, val=1.0):
    """HSV to '#rrggbb', hue wrapping so it can drift past 1.0."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1.0, max(0.0, sat)),
                                  min(1.0, max(0.0, val)))
    return "#{:02x}{:02x}{:02x}".format(
        round(r * 255), round(g * 255), round(b * 255))


def lerp_hex(c1, c2, t):
    t = min(1.0, max(0.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return "#{:02x}{:02x}{:02x}".format(
        round(r1 + (r2 - r1) * t),
        round(g1 + (g2 - g1) * t),
        round(b1 + (b2 - b1) * t))


def now_hue(offset=0.0, speed=0.05):
    """A slowly drifting rainbow phase for animations."""
    return (_clock.perf_counter() * speed + offset) % 1.0


def rainbow_label(label, speed=0.06, offset=0.0, sat=0.85, val=1.0,
                  period_ms=90):
    """Keep a label's foreground cycling through the spectrum."""

    def tick():
        try:
            if not label.winfo_exists():
                return
            label.config(fg=hsv_hex(now_hue(offset, speed), sat, val))
        except Exception:
            return
        label.after(period_ms, tick)

    tick()


def gradient_rect(canvas, x0, y0, x1, y1, r, top, bottom, steps=12):
    """Vertical gradient inside a rounded rect.

    Canvas has no clipping, so the bands only span the straight middle of the
    shape; the corners keep the solid bottom colour and the eye reads it as
    one smooth fill.
    """
    round_rect(canvas, x0, y0, x1, y1, r, fill=bottom, outline=bottom)
    band_top, band_bot = y0 + r, y1 - r
    span = band_bot - band_top
    if span > 0:
        step = span / steps
        for i in range(steps):
            colour = lerp_hex(top, bottom, i / max(1, steps - 1))
            ya = band_top + i * step
            canvas.create_rectangle(x0, ya, x1, ya + step + 1,
                                    fill=colour, outline=colour)


class WavyTitle(tk.Canvas):
    """App title with hue-cycling text over animated rainbow waves."""

    def __init__(self, parent, text, size=21, bg=BG):
        self.text = text
        self.size = size
        f = tkfont.Font(family=FONT, size=size, weight="bold")
        width = f.measure(text) + s(18)
        height = s(size * 1.5) + s(34)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self._cw, self._ch = width, height
        self._animate()

    def _animate(self):
        try:
            if not self.winfo_exists():
                return
            self._paint()
        except Exception:
            return
        self.after(66, self._animate)

    def _paint(self):
        import math
        self.delete("all")
        w, h = self._cw, self._ch
        text_y = s(self.size * 0.85) + s(4)
        self.create_text(w / 2, text_y, text=self.text,
                         fill=hsv_hex(now_hue(0.0, 0.08), 0.80, 1.0),
                         font=(FONT, self.size, "bold"))
        base_y = h - s(16)
        for k in range(3):
            amp = s(3) + k * s(1.4)
            phase = _clock.perf_counter() * (2.4 + 0.6 * k) + k * 2.1
            pts = []
            for step in range(25):
                x = s(3) + (step / 24) * (w - s(6))
                y = base_y + k * s(4) + amp * math.sin(step * 0.75 + phase)
                pts += [x, y]
            self.create_line(*pts, smooth=True, width=max(2, s(2)),
                             fill=hsv_hex(now_hue(k * 0.13, 0.10), 0.9, 0.95))


class RainbowBand(tk.Canvas):
    """Full-width split-fountain gradient band with the title living on it."""

    def __init__(self, parent, title, tagline="", height=78, bg=BG):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self._title = title
        self._tagline = tagline
        self._cw = 1
        self._ch = s(height)
        self.configure(height=self._ch)
        self.bind("<Configure>", lambda e: setattr(self, "_cw", e.width))
        self._animate()

    def _animate(self):
        try:
            if not self.winfo_exists():
                return
            if self._cw > 2:
                self._paint()
        except Exception:
            return
        self.after(66, self._animate)

    def _paint(self):
        import math
        self.delete("all")
        w, h = self._cw, self._ch
        base = now_hue(0.55, 0.04)
        bands = 40
        bw = w / bands
        for i in range(bands):
            hue = base + (i / bands) * 0.28
            colour = hsv_hex(hue, 0.80, 0.34)
            self.create_rectangle(i * bw, 0, (i + 1) * bw + 1, h,
                                  fill=colour, outline=colour)
        for k in range(3):
            pts = []
            amp = s(2.5) + k * s(1.2)
            phase = _clock.perf_counter() * (2.2 + 0.5 * k) + k * 2.0
            for step in range(30):
                x = (step / 29) * w
                y = h - s(9) + k * s(3) + amp * math.sin(step * 0.8 + phase)
                pts += [x, y]
            self.create_line(*pts, smooth=True, width=max(2, s(2)),
                             fill=hsv_hex(now_hue(k * 0.12, 0.15), 0.9, 1.0))
        ty = s(24)
        self.create_text(w / 2 + s(2), ty + s(2), text=self._title,
                         fill="#12081f", font=(FONT, 22, "bold"))
        self.create_text(w / 2, ty, text=self._title, fill="#ffffff",
                         font=(FONT, 22, "bold"))
        if self._tagline:
            self.create_text(w / 2, ty + s(26), text=self._tagline,
                             fill="#e8dcff", font=(FONT, 9))


class PlasmaStrip(tk.Canvas):
    """Liquid-light-show strip: real animated plasma where numpy + Pillow
    are available, drifting gradient bands as the fallback."""

    def __init__(self, parent, height=52, text="", radius=14, bg=CARD):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self._ch = s(height)
        self._text = text
        self._radius = s(radius)
        self._cw = 1
        self.configure(height=self._ch)
        self.bind("<Configure>", lambda e: setattr(self, "_cw", e.width))
        self._photo = None
        try:
            import numpy as np
            from PIL import Image, ImageDraw, ImageTk
            self._np = np
            self._PILImage = Image
            self._PILDraw = ImageDraw
            self._ImageTk = ImageTk
            self._plasma = True
        except Exception:
            self._plasma = False
        self._animate()

    def _animate(self):
        try:
            if not self.winfo_exists():
                return
            if self._cw > 2:
                self._paint()
        except Exception:
            return
        self.after(50, self._animate)

    def _plasma_image(self, w, h):
        np = self._np
        t = _clock.perf_counter() * 0.6
        lw, lh = max(24, w // 10), max(8, h // 10)
        y, x = np.mgrid[0:lh, 0:lw]
        u = x / lw * 6.283
        v = y / lh * 6.283
        val = (np.sin(u * 1.3 + t) + np.sin(v * 1.7 - t * 1.3)
               + np.sin((u + v) * 0.9 + t * 0.7)
               + np.sin(np.hypot(u - 3.1, v - 1.6) * 1.4 - t * 1.1))
        span = float(val.max() - val.min()) or 1.0
        hue = ((val - val.min()) / span * 0.85 + t * 0.04) % 1.0
        sat = 0.80
        k6 = hue * 6
        i = k6.astype(int) % 6
        f = k6 - k6.astype(int)
        one = np.ones_like(f)
        zero = np.zeros_like(f)
        q = 1 - sat * f
        tv = 1 - sat * (1 - f)
        r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                      [one, q, zero, zero, tv, one])
        g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                      [tv, one, one, q, zero, zero])
        b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                      [zero, zero, tv, one, one, q])
        rgb = (np.dstack([r, g, b]) * 255).astype("uint8")
        img = self._PILImage.fromarray(rgb).resize((w, h), self._PILImage.BILINEAR)
        mask = self._PILImage.new("L", (w, h), 0)
        md = self._PILDraw.Draw(mask)
        md.rounded_rectangle([0, 0, w - 1, h - 1], radius=self._radius, fill=255)
        md.rectangle([0, h // 2, w - 1, h - 1], fill=255)
        img.putalpha(mask)
        return img

    def _paint(self):
        import math
        self.delete("all")
        w, h = self._cw, self._ch
        if self._plasma:
            img = self._plasma_image(w, h)
            self._photo = self._ImageTk.PhotoImage(img)
            self.create_image(0, 0, image=self._photo, anchor="nw")
        else:
            base = now_hue(0.2, 0.08)
            bands = 32
            bw = w / bands
            for i in range(bands):
                colour = hsv_hex(base + (i / bands) * 0.35, 0.8, 0.45)
                self.create_rectangle(i * bw, 0, (i + 1) * bw + 1, h,
                                      fill=colour, outline=colour)
        if self._text:
            ty = h / 2 - s(2)
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                self.create_text(w / 2 + dx, ty + dy, text=self._text,
                                 fill="#12081f", font=(FONT, 9, "bold"))
            self.create_text(w / 2, ty, text=self._text, fill="#ffffff",
                             font=(FONT, 9, "bold"))


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
        self._hue = (_clock.perf_counter() * 0.37) % 1.0
        self.bind("<Configure>", self._redraw)
        if self._autosize:
            self.body.bind("<Configure>", self._fit)
        self._animate()

    def _fit(self, _event=None):
        want = self.body.winfo_reqheight() + 2
        if want > 12 and abs(want - int(self["height"])) > 1:
            self.configure(height=want)

    def _animate(self):
        try:
            if not self.winfo_exists():
                return
            if self.winfo_width() > 2 and self.winfo_height() > 2:
                self._paint(self.winfo_width(), self.winfo_height())
        except Exception:
            return
        self.after(120, self._animate)

    def _redraw(self, event):
        self._paint(event.width, event.height)

    def _paint(self, w, h):
        self.delete("bg")
        edge = hsv_hex(now_hue(self._hue, 0.03), 0.75, 0.55)
        round_rect(self, -1, -1, w, h, 15, outline=edge, tags="bg")
        round_rect(self, 0, 0, w - 1, h - 1, 14,
                   fill=CARD, outline=LINE, tags="bg")
        self.tag_lower("bg")
        self.coords(self._win, 1, 1)
        self.itemconfig(self._win, width=w - 2, height=h - 2)


class Toggle(tk.Canvas):
    """iOS-style switch bound to a tk.BooleanVar."""

    def __init__(self, parent, variable, command=None, help_text=None):
        self.W, self.H = s(44), s(24)
        super().__init__(parent, width=self.W, height=self.H, bg=CARD,
                         highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.var = variable
        self.command = command
        self.bind("<Button-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()
        if help_text:
            self.tooltip = Tooltip(self, help_text)

    def _click(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        if on:
            gradient_rect(self, 1, 1, self.W - 1, self.H - 1,
                          (self.H - 2) / 2, ACCENT, GRAD_B, steps=6)
        else:
            round_rect(self, 1, 1, self.W - 1, self.H - 1, (self.H - 2) / 2,
                       fill="#33224f", outline="#33224f")
        r = (self.H - s(8)) / 2
        cx = (self.W - r - s(5)) if on else (r + s(5))
        cy = self.H / 2
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#ffffff",
                         outline="#ffffff")


class Segmented(tk.Canvas):
    """Two-or-more option selector bound to a tk.StringVar."""

    def __init__(self, parent, options, variable, width=300, height=34,
                 command=None, labels=None, help_text=None):
        width, height = s(width), s(height)
        super().__init__(parent, width=width, height=height, bg=CARD,
                         highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.options = list(options)
        self.var = variable
        self.command = command
        self.labels = labels or {}
        self._cw, self._ch = width, height
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()
        if help_text:
            self.tooltip = Tooltip(self, help_text)

    def _click(self, event):
        idx = int(event.x // (self._cw / len(self.options)))
        idx = max(0, min(idx, len(self.options) - 1))
        self.var.set(self.options[idx])
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        round_rect(self, 0, 0, self._cw - 1, self._ch - 1, 9,
                   fill="#120a20", outline=LINE)
        seg = self._cw / len(self.options)
        for i, opt in enumerate(self.options):
            x0 = i * seg
            active = self.var.get() == opt
            if active:
                gradient_rect(self, x0 + 3, 3, x0 + seg - 3, self._ch - 3, 7,
                              ACCENT, GRAD_B, steps=6)
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
        self.peaks = [0.0] * bars
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
        self.peaks = [0.0] * self.bars

    def draw(self):
        import math
        self.delete("all")
        n = self.bars
        gap = 3
        bw = max(2, (self._cw - gap * (n - 1)) / n)
        mid = self._ch / 2
        base = now_hue(0.0, 0.10)
        for i, lvl in enumerate(self.levels[-n:]):
            db = 20 * math.log10(max(lvl, 1e-6))
            frac = max(0.03, min(1.0, (db + 60) / 60))
            self.peaks[i] = max(self.peaks[i] * 0.93, frac)
            bh = max(2, frac * (self._ch - 10))
            x = i * (bw + gap)
            if self.active:
                colour = hsv_hex(base + (i / n) * 0.45, 0.85,
                                 0.35 + 0.6 * frac)
            else:
                colour = "#241a38"
            self.create_rectangle(x, mid - bh / 2, x + bw, mid + bh / 2,
                                  fill=colour, outline=colour)
            if self.active and self.peaks[i] > 0.08:
                py = mid - max(2, self.peaks[i] * (self._ch - 10)) / 2
                pr = max(1, bw / 3)
                self.create_oval(x + bw / 2 - pr, py - pr,
                                 x + bw / 2 + pr, py + pr,
                                 fill="#ffffff", outline="#ffffff")


class Button(tk.Canvas):
    """Flat rounded button."""

    def __init__(self, parent, text, command, primary=False, width=110,
                 height=34, bg=CARD, help_text=None):
        width, height = s(width), s(height)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.text, self.command = text, command
        self.primary = primary
        self._cw, self._ch = width, height
        self._hover = False
        self.pulse = False
        self._pulse_job = None
        self.bind("<Button-1>", lambda _e: self.command())
        self.bind("<Return>", lambda _e: self.command())
        self.bind("<space>", lambda _e: self.command())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._draw()
        if help_text:
            self.tooltip = Tooltip(self, help_text)

    def set_text(self, text):
        """Change the label without rebuilding the button."""
        self.text = text
        self._draw()

    def set_pulse(self, on):
        """Animate a rainbow ring around the button while on."""
        self.pulse = bool(on)
        if self.pulse and self._pulse_job is None:
            self._pulse_loop()
        elif not self.pulse and self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
            self._draw()

    def _pulse_loop(self):
        try:
            if not self.winfo_exists() or not self.pulse:
                self._pulse_job = None
                if self.winfo_exists():
                    self._draw()
                return
            self._draw()
        except Exception:
            self._pulse_job = None
            return
        self._pulse_job = self.after(90, self._pulse_loop)

    def _enter(self, _e):
        self._hover = True
        self._draw()

    def _leave(self, _e):
        self._hover = False
        self._draw()

    def _draw(self):
        self.delete("all")
        if self.primary:
            lift = 0.18 if self._hover else 0.0
            top = lerp_hex(ACCENT, "#ffffff", lift)
            bot = lerp_hex(GRAD_B, "#ffffff", lift)
            gradient_rect(self, 0, 0, self._cw - 1, self._ch - 1, 9,
                          top, bot)
            if self.pulse:
                ring = hsv_hex(now_hue(0.0, 0.30), 0.9, 1.0)
                round_rect(self, -1, -1, self._cw, self._ch, 10,
                           outline=ring)
            fg = "#ffffff"
        else:
            fill = CARD_HI if self._hover else "#201233"
            outline = ACCENT if self._hover else LINE
            round_rect(self, 0, 0, self._cw - 1, self._ch - 1, 9,
                       fill=fill, outline=outline)
            fg = TEXT
        self.create_text(self._cw / 2, self._ch / 2, text=self.text, fill=fg,
                         font=(FONT, 9, "bold"))
