"""
The look of Flow: palette, type, and the hand-drawn widgets the app is built from.

Stock ttk cannot be styled into anything modern on Windows, so anything with a
custom shape (cards, switches, segmented controls, key caps, buttons) is drawn
here instead.

Tk's own Canvas has no anti-aliasing, which is what made the earlier version of
this look home-made: every rounded corner was a staircase and every gradient
was a stack of visible bands. So shapes are rendered with Pillow at 4x and
scaled down, then handed to the Canvas as a single image. Pillow is optional -
if it is missing every widget falls back to the old aliased Canvas drawing and
the app still runs.
"""

import colorsys
import ctypes
import math
import time as _clock
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk
    HAVE_PIL = True
except Exception:                                    # pragma: no cover
    HAVE_PIL = False


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


# palette -------------------------------------------------------------------
# One dark plum ground, one violet->magenta->cyan ribbon of accent. The colour
# stays loud; what changed is that the loud parts are now reserved for the few
# things that should pull the eye (the wordmark, the primary button, the live
# waveform) instead of being sprayed over every border at once.
BG = "#0A0614"          # window ground
BG_SOFT = "#120A24"     # top of the window's vertical wash
CARD = "#171029"        # raised surface
CARD_HI = "#231640"     # hover / key caps
FIELD = "#0E0820"       # text inputs and lists, recessed
LINE = "#2E1F55"        # quiet border
LINE_HI = "#54399A"     # lit top edge of a border
TEXT = "#F4EEFF"
MUTED = "#9C8CC4"
ACCENT = "#FF5AD8"      # magenta
ACCENT_2 = "#4BE9FF"    # cyan
GOOD = "#4CEFA6"
WARN = "#FFC94A"
REC = "#FF5C74"
GRAD_B = "#7C5CFF"      # violet, the midpoint of the accent ribbon

# Comic Sans was the single loudest "made at home" signal in the old design.
# Segoe UI ships on every Windows this app supports, so it always resolves.
FONT = "Segoe UI"
_DISPLAY_FONT_FILES = (
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
)

SS = 4                  # supersample factor for every drawn shape
_CACHE = {}             # (key) -> PhotoImage, so animation does not re-render


def _rgb(colour):
    return (int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16))


def _hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(round(c))))
                                          for c in rgb))


def hsv_hex(h, sat=0.85, val=1.0):
    """HSV to '#rrggbb', hue wrapping so it can drift past 1.0."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1.0, max(0.0, sat)),
                                  min(1.0, max(0.0, val)))
    return "#{:02x}{:02x}{:02x}".format(
        round(r * 255), round(g * 255), round(b * 255))


def lerp_hex(c1, c2, t):
    t = min(1.0, max(0.0, t))
    r1, g1, b1 = _rgb(c1)
    r2, g2, b2 = _rgb(c2)
    return _hex((r1 + (r2 - r1) * t,
                 g1 + (g2 - g1) * t,
                 b1 + (b2 - b1) * t))


def mix(c1, c2, t):
    """Readable alias for lerp_hex, used all over this module."""
    return lerp_hex(c1, c2, t)


def now_hue(offset=0.0, speed=0.05):
    """A slowly drifting rainbow phase for animations."""
    return (_clock.perf_counter() * speed + offset) % 1.0


def ribbon(t):
    """Sample the brand gradient (magenta -> violet -> cyan) at 0..1."""
    t = t % 1.0
    if t < 0.5:
        return lerp_hex(ACCENT, GRAD_B, t / 0.5)
    return lerp_hex(GRAD_B, ACCENT_2, (t - 0.5) / 0.5)


# ------------------------------------------------------------- rendering ----
def _cached(key, build):
    """Render once, reuse forever. Animations redraw far too often to not."""
    img = _CACHE.get(key)
    if img is None:
        if len(_CACHE) > 400:
            _CACHE.clear()
        img = build()
        _CACHE[key] = img
    return img


def _vgradient(size, top, bottom):
    """A vertical two-stop gradient as an RGB image."""
    w, h = size
    strip = Image.new("RGB", (1, h))
    t_rgb, b_rgb = _rgb(top), _rgb(bottom)
    px = strip.load()
    for y in range(h):
        f = y / max(1, h - 1)
        px[0, y] = tuple(int(round(t_rgb[i] + (b_rgb[i] - t_rgb[i]) * f))
                         for i in range(3))
    return strip.resize((w, h), Image.NEAREST)


def _hgradient(size, stops):
    """A horizontal multi-stop gradient as an RGB image."""
    w, h = size
    strip = Image.new("RGB", (w, 1))
    px = strip.load()
    n = len(stops) - 1
    for x in range(w):
        f = (x / max(1, w - 1)) * n
        i = min(n - 1, int(f))
        a, b = _rgb(stops[i]), _rgb(stops[i + 1])
        local = f - i
        px[x, 0] = tuple(int(round(a[j] + (b[j] - a[j]) * local))
                         for j in range(3))
    return strip.resize((w, h), Image.NEAREST)


def panel_image(w, h, radius, fill, bg=BG, fill_bottom=None,
                border=None, border_top=None, border_w=1,
                glow=None, glow_r=0, glow_alpha=90, inset=0):
    """A rounded panel, anti-aliased, flattened onto `bg`.

    Everything is drawn at SS times the final size and scaled back down, which
    is the whole reason the corners stop looking like stairs. `bg` has to be
    the colour actually sitting behind the widget because a Tk Canvas cannot
    hold real transparency - the image is opaque by the time Tk sees it.
    """
    if w < 4 or h < 4:
        return None
    # Tk hands out placeholder sizes (a card is 10px tall for one frame while
    # the layout settles), and Pillow rejects a box that has inverted or a
    # radius larger than half of it. Shrink the decoration to fit rather than
    # letting a transient size raise.
    inset = max(0, min(inset, (min(w, h) - 3) // 2))
    radius = max(0, min(int(radius), (min(w, h) - 2 * inset - 1) // 2))

    key = ("panel", w, h, radius, fill, bg, fill_bottom, border, border_top,
           border_w, glow, glow_r, glow_alpha, inset)

    def build():
        base = Image.new("RGB", (w, h), _rgb(bg))
        x0, y0 = inset, inset
        x1, y1 = w - 1 - inset, h - 1 - inset

        if glow and glow_r > 0:
            # A blurred copy of the silhouette, sitting behind the panel. This
            # is what stops the accent colours reading as flat stickers.
            gm = Image.new("L", (w, h), 0)
            ImageDraw.Draw(gm).rounded_rectangle(
                (x0, y0, x1, y1), radius=radius, fill=glow_alpha)
            gm = gm.filter(ImageFilter.GaussianBlur(glow_r))
            base = Image.composite(Image.new("RGB", (w, h), _rgb(glow)),
                                   base, gm)

        # The panel itself, supersampled.
        bw, bh = w * SS, h * SS
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (x0 * SS, y0 * SS, x1 * SS + SS - 1, y1 * SS + SS - 1),
            radius=radius * SS, fill=255)
        body = (_vgradient((bw, bh), fill, fill_bottom) if fill_bottom
                else Image.new("RGB", (bw, bh), _rgb(fill)))

        if border:
            # Light the border from the top, the way a real bevel is lit.
            edge = Image.new("L", (bw, bh), 0)
            ImageDraw.Draw(edge).rounded_rectangle(
                (x0 * SS, y0 * SS, x1 * SS + SS - 1, y1 * SS + SS - 1),
                radius=radius * SS, outline=255, width=max(1, border_w * SS))
            body.paste(_vgradient((bw, bh), border_top or border, border),
                       mask=edge)

        body = body.resize((w, h), Image.LANCZOS)
        mask = mask.resize((w, h), Image.LANCZOS)
        base.paste(body, mask=mask)
        return ImageTk.PhotoImage(base)

    return _cached(key, build)


def gradient_text_image(text, px, stops, bg=BG, glow=None, pad=6):
    """The wordmark: real type filled with the brand ribbon, plus a soft halo."""
    key = ("gtext", text, px, tuple(stops), bg, glow, pad)

    def build():
        font = _display_font(px)
        tmp = ImageDraw.Draw(Image.new("L", (1, 1)))
        left, top, right, bottom = tmp.textbbox((0, 0), text, font=font)
        w = right - left + pad * 2
        h = bottom - top + pad * 2
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).text((pad - left, pad - top), text, font=font,
                                  fill=255)
        base = Image.new("RGB", (w, h), _rgb(bg))
        if glow:
            halo = mask.filter(ImageFilter.GaussianBlur(px * 0.12))
            halo = halo.point(lambda v: int(v * 0.55))
            base = Image.composite(Image.new("RGB", (w, h), _rgb(glow)),
                                   base, halo)
        base.paste(_hgradient((w, h), stops), mask=mask)
        return ImageTk.PhotoImage(base)

    return _cached(key, build)


_display_font_cache = {}


def _display_font(px):
    font = _display_font_cache.get(px)
    if font is None:
        for path in _DISPLAY_FONT_FILES:
            try:
                font = ImageFont.truetype(path, px)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        _display_font_cache[px] = font
    return font


class _Painted(tk.Canvas):
    """Canvas that swaps a single rendered image, keeping the reference alive."""

    def _blit(self, image):
        if image is None:
            return
        self._image = image                 # Tk drops un-referenced images
        if getattr(self, "_item", None) is None:
            self._item = self.create_image(0, 0, image=image, anchor="nw")
        else:
            self.itemconfig(self._item, image=image)
            self.tag_lower(self._item)


# ------------------------------------------------------------ primitives ----
def round_rect(canvas, x0, y0, x1, y1, r, **kw):
    """Rounded rectangle as a smoothed polygon (fallback path, no Pillow)."""
    r = min(r, abs(x1 - x0) / 2, abs(y1 - y0) / 2)
    pts = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


def gradient_rect(canvas, x0, y0, x1, y1, r, top, bottom, steps=12):
    """Vertical gradient inside a rounded rect (fallback path, no Pillow)."""
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


def rainbow_label(label, speed=0.06, offset=0.0, sat=0.85, val=1.0,
                  period_ms=90):
    """Keep a label's foreground drifting along the brand ribbon.

    Deliberately slower and less saturated than a full-spectrum cycle - the
    old version strobed, which is both harder to read and the thing that made
    the app look like a screensaver.
    """

    def tick():
        try:
            if not label.winfo_exists():
                return
            label.config(fg=ribbon(now_hue(offset, speed * 0.5)))
        except Exception:
            return
        label.after(period_ms, tick)

    tick()


# ---------------------------------------------------------------- chrome ----
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
            frame = tk.Frame(tip, bg=LINE_HI)
            frame.pack()
            tk.Label(
                frame, text=self.text, bg=CARD_HI, fg=TEXT,
                font=(FONT, 9), justify="left", wraplength=s(300),
                padx=s(11), pady=s(8),
            ).pack(padx=1, pady=1)
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
        # Windows 11 also lets the frame itself be tinted, which is what makes
        # the title bar read as part of the app rather than bolted on.
        for attr, colour in ((35, BG), (34, LINE)):       # CAPTION, BORDER
            r, g, b = _rgb(colour)
            value = ctypes.c_int(b << 16 | g << 8 | r)    # DWM wants 0x00BBGGRR
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def style_ttk(root):
    """Drag the one ttk widget in the app (the microphone list) into the dark."""
    try:
        from tkinter import ttk
        st = ttk.Style(root)
        try:
            st.theme_use("clam")             # the only theme that takes colour
        except Exception:
            pass
        st.configure(
            "TCombobox", fieldbackground=FIELD, background=FIELD,
            foreground=TEXT, arrowcolor=MUTED, bordercolor=LINE,
            lightcolor=LINE, darkcolor=LINE, insertcolor=TEXT,
            relief="flat", padding=s(6), arrowsize=s(14),
        )
        st.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD)],
            background=[("active", FIELD), ("readonly", FIELD)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", FIELD)],
            selectforeground=[("readonly", TEXT)],
            bordercolor=[("focus", ACCENT), ("hover", LINE_HI)],
            arrowcolor=[("active", ACCENT)],
        )
        root.option_add("*TCombobox*Listbox.background", FIELD)
        root.option_add("*TCombobox*Listbox.foreground", TEXT)
        root.option_add("*TCombobox*Listbox.selectBackground", GRAD_B)
        root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        root.option_add("*TCombobox*Listbox.borderWidth", 0)
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


# --------------------------------------------------------------- widgets ----
class WavyTitle(_Painted):
    """The Flow wordmark: gradient type over slow aurora waves."""

    def __init__(self, parent, text, size=21, bg=BG):
        self.text = text
        self.size = size
        self._bg = bg
        self._px = max(12, int(round(size * SCALE * 96 / 72)))
        self._frame = 0

        if HAVE_PIL:
            probe = gradient_text_image(text, self._px,
                                        (ACCENT, GRAD_B, ACCENT_2), bg=bg,
                                        glow=GRAD_B, pad=s(7))
            width = probe.width()
            text_h = probe.height()
        else:
            f = tkfont.Font(family=FONT, size=size, weight="bold")
            width = f.measure(text) + s(18)
            text_h = s(size * 1.4)

        height = text_h + s(16)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self._cw, self._ch = width, height
        self._text_h = text_h
        self._item = None
        self._animate()

    def _animate(self):
        try:
            if not self.winfo_exists():
                return
            self._paint()
        except Exception:
            return
        self.after(70, self._animate)

    def _paint(self):
        self._frame += 1
        self.delete("wave")

        if HAVE_PIL:
            # 30 pre-rendered phases is plenty to read as motion, and means the
            # wordmark is rendered 30 times ever rather than 14 times a second.
            phase = int(now_hue(0.0, 0.045) * 30) / 30.0
            stops = (ribbon(phase), ribbon(phase + 0.33), ribbon(phase + 0.66))
            self._blit(gradient_text_image(self.text, self._px, stops,
                                           bg=self._bg, glow=GRAD_B, pad=s(7)))
        else:
            self.delete("txt")
            self.create_text(self._cw / 2, self._text_h / 2, text=self.text,
                             fill=ribbon(now_hue(0.0, 0.05)), tags="txt",
                             font=(FONT, self.size, "bold"))

        base_y = self._text_h + s(2)
        for k in range(3):
            # Small amplitudes and a wide gap keep the three strands reading as
            # parallel currents; larger ones tangle into a knot.
            amp = s(1.4) + k * s(0.5)
            phase = _clock.perf_counter() * (1.5 + 0.4 * k) + k * 2.1
            pts = []
            for step in range(29):
                x = s(6) + (step / 28) * (self._cw - s(12))
                y = base_y + k * s(4.0) + amp * math.sin(step * 0.55 + phase)
                pts += [x, y]
            self.create_line(*pts, smooth=True, width=max(1, s(1.5)),
                             tags="wave",
                             fill=mix(ribbon(now_hue(k * 0.18, 0.045)),
                                      self._bg, 0.15 + 0.22 * k))


class Card(_Painted):
    """A rounded panel you can pack normal widgets into via .body.

    Height follows the content unless one is given explicitly - fixed heights
    silently clip trailing labels when fonts scale on a high-DPI display.
    """

    # The body is a square frame, so it has to sit far enough in that its
    # corners stay inside the rounded outline: inset + 0.3 * radius.
    PAD = 10

    def __init__(self, parent, height=None, autosize=True, bg=BG,
                 accent=None, **kw):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0,
                         height=height or 10, **kw)
        self._bg = bg
        self._accent = accent or GRAD_B
        self._pad = s(self.PAD)
        self._item = None
        self.body = tk.Frame(self, bg=CARD)
        self._win = self.create_window(self._pad, self._pad, window=self.body,
                                       anchor="nw")
        self._autosize = autosize and height is None
        self._last = None
        self.bind("<Configure>", self._redraw)
        if self._autosize:
            self.body.bind("<Configure>", self._fit)
            # The body sits in a canvas window item with an explicit size, so
            # Tk stops sending it <Configure> once content is added later -
            # a card built before its labels would stay at its stub height.
            # Re-checking on a slow timer also picks up text that rewraps.
            self._poll()

    def _poll(self):
        try:
            if not self.winfo_exists():
                return
            self._fit()
        except Exception:
            return
        self.after(200, self._poll)

    def _fit(self, _event=None):
        want = self.body.winfo_reqheight() + self._pad * 2
        if want > 12 and abs(want - int(self["height"])) > 1:
            self.configure(height=want)

    def _redraw(self, event):
        self._paint(event.width, event.height)

    def _paint(self, w, h):
        if (w, h) == self._last or w < 4 or h < 4:
            self._place_body(w, h)
            return
        self._last = (w, h)
        if HAVE_PIL:
            self._blit(panel_image(
                w, h, radius=s(14), fill=CARD, bg=self._bg,
                border=LINE, border_top=LINE_HI, border_w=1,
                glow=self._accent, glow_r=s(4), glow_alpha=64, inset=s(5)))
        else:
            self.delete("bg")
            round_rect(self, 0, 0, w - 1, h - 1, s(14),
                       fill=CARD, outline=LINE, tags="bg")
            self.tag_lower("bg")
        self._place_body(w, h)

    def _place_body(self, w, h):
        self.coords(self._win, self._pad, self._pad)
        self.itemconfig(self._win, width=max(1, w - self._pad * 2),
                        height=max(1, h - self._pad * 2))


class Button(_Painted):
    """Rounded button. Primary carries the brand gradient and a soft glow."""

    def __init__(self, parent, text, command, primary=False, width=110,
                 height=34, bg=CARD, help_text=None):
        width, height = s(width), s(height)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.text, self.command = text, command
        self.primary = primary
        self.tone = None                    # optional colour override
        self._bg = bg
        self._cw, self._ch = width, height
        self._hover = False
        self._down = False
        self._item = None
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", lambda _e: self.command())
        self.bind("<space>", lambda _e: self.command())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._enter)
        self.bind("<FocusOut>", self._leave)
        self._draw()
        if help_text:
            self.tooltip = Tooltip(self, help_text)

    def set_text(self, text):
        """Change the label without rebuilding the button."""
        self.text = text
        self._draw()

    def set_tone(self, colour=None):
        """Recolour a primary button, e.g. red while it is recording."""
        self.tone = colour
        self._draw()

    def _press(self, _e):
        self._down = True
        self._draw()

    def _release(self, _e):
        was_down = self._down
        self._down = False
        self._draw()
        if was_down:
            self.command()

    def _enter(self, _e=None):
        self._hover = True
        self._draw()

    def _leave(self, _e=None):
        self._hover = False
        self._down = False
        self._draw()

    def _draw(self):
        w, h = self._cw, self._ch
        r = s(10)
        lift = 0.0 if self._down else (0.16 if self._hover else 0.0)
        sink = 0.10 if self._down else 0.0

        if self.primary:
            a = mix(self.tone or ACCENT, "#ffffff", lift)
            b = mix(self.tone or GRAD_B, "#ffffff", lift)
            if self.tone:
                b = mix(self.tone, "#000000", 0.22)
            a, b = mix(a, "#000000", sink), mix(b, "#000000", sink)
            fg = "#ffffff"
        else:
            a = CARD_HI if (self._hover and not self._down) else mix(CARD, BG, 0.35)
            b = mix(a, "#000000", 0.18)
            fg = TEXT

        if HAVE_PIL:
            # The glow has to fade out inside the canvas, so its blur radius
            # stays under the inset - otherwise it hits the edge still bright
            # and the button wears a visible rectangle.
            if self.primary:
                img = panel_image(
                    w, h, r, fill=a, fill_bottom=b, bg=self._bg,
                    border=mix(b, "#000000", 0.25),
                    border_top=mix(a, "#ffffff", 0.40),
                    glow=self.tone or ACCENT, glow_r=s(2.5),
                    glow_alpha=120 if self._hover else 80, inset=s(4))
            else:
                img = panel_image(
                    w, h, r, fill=a, fill_bottom=b, bg=self._bg,
                    border=ACCENT if self._hover else LINE,
                    border_top=mix(ACCENT_2, ACCENT, 0.5) if self._hover else LINE_HI,
                    glow=ACCENT if self._hover else None,
                    glow_r=s(2.5), glow_alpha=70, inset=s(4))
            self._blit(img)
        else:
            self.delete("bg")
            if self.primary:
                gradient_rect(self, 0, 0, w - 1, h - 1, s(9), a, b)
            else:
                round_rect(self, 0, 0, w - 1, h - 1, s(9), fill=a,
                           outline=ACCENT if self._hover else LINE, tags="bg")

        self.delete("label")
        size = 10 if h >= s(42) else 9
        self.create_text(w / 2, h / 2 + (1 if self._down else 0),
                         text=self.text, fill=fg, tags="label",
                         font=(FONT, size, "bold"))


class Toggle(_Painted):
    """iOS-style switch bound to a tk.BooleanVar, with an eased slide."""

    STEPS = 7

    def __init__(self, parent, variable, command=None, help_text=None):
        self.W, self.H = s(46), s(26)
        super().__init__(parent, width=self.W, height=self.H, bg=CARD,
                         highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.var = variable
        self.command = command
        self._pos = 1.0 if variable.get() else 0.0
        self._job = None
        self._item = None
        self.bind("<Button-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self.var.trace_add("write", lambda *_: self._animate())
        self._draw()
        if help_text:
            self.tooltip = Tooltip(self, help_text)

    def _click(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _animate(self):
        target = 1.0 if self.var.get() else 0.0
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        start = self._pos

        def step(i=1):
            self._job = None
            f = i / self.STEPS
            f = 1 - (1 - f) ** 3                     # ease-out, never overshoots
            self._pos = start + (target - start) * f
            self._draw()
            if i < self.STEPS and self.winfo_exists():
                self._job = self.after(16, step, i + 1)

        step()

    def _draw(self):
        p = max(0.0, min(1.0, self._pos))
        w, h = self.W, self.H
        r = (h - s(2)) / 2

        if HAVE_PIL:
            track = mix("#2A1C4E", ACCENT, p)
            track_b = mix("#1D1338", GRAD_B, p)
            self._blit(panel_image(
                w, h, int(r), fill=track, fill_bottom=track_b, bg=CARD,
                border=mix(LINE, mix(GRAD_B, "#000000", 0.25), p),
                border_top=mix(LINE_HI, mix(ACCENT, "#ffffff", 0.3), p),
                glow=ACCENT if p > 0.5 else None, glow_r=s(6),
                glow_alpha=int(90 * p), inset=s(1)))
        else:
            self.delete("bg")
            round_rect(self, 1, 1, w - 1, h - 1, r,
                       fill=mix("#33224f", ACCENT, p),
                       outline=mix(LINE, ACCENT, p), tags="bg")

        self.delete("knob")
        kr = (h - s(9)) / 2
        cx = (kr + s(5)) + p * (w - 2 * kr - s(10))
        cy = h / 2
        self.create_oval(cx - kr - 1, cy - kr + 1, cx + kr + 1, cy + kr + 2,
                         fill=mix(BG, CARD, 0.4), outline="", tags="knob")
        self.create_oval(cx - kr, cy - kr, cx + kr, cy + kr,
                         fill="#ffffff", outline="", tags="knob")


class Segmented(_Painted):
    """Two-or-more option selector bound to a tk.StringVar, with a sliding thumb."""

    STEPS = 6

    def __init__(self, parent, options, variable, width=300, height=34,
                 command=None, labels=None, help_text=None, bg=CARD):
        width, height = s(width), s(height)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.options = list(options)
        self.var = variable
        self.command = command
        self.labels = labels or {}
        self._bg = bg
        self._cw, self._ch = width, height
        self._item = None
        self._job = None
        self._hover = -1
        try:
            self._pos = float(self.options.index(variable.get()))
        except ValueError:
            self._pos = 0.0
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.var.trace_add("write", lambda *_: self._animate())
        self._draw()
        if help_text:
            self.tooltip = Tooltip(self, help_text)

    def _index_at(self, x):
        idx = int(x // (self._cw / len(self.options)))
        return max(0, min(idx, len(self.options) - 1))

    def _click(self, event):
        self.var.set(self.options[self._index_at(event.x)])
        if self.command:
            self.command()

    def _motion(self, event):
        idx = self._index_at(event.x)
        if idx != self._hover:
            self._hover = idx
            self._draw()

    def _leave(self, _e):
        self._hover = -1
        self._draw()

    def _animate(self):
        try:
            target = float(self.options.index(self.var.get()))
        except ValueError:
            return
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        start = self._pos

        def step(i=1):
            self._job = None
            f = i / self.STEPS
            f = 1 - (1 - f) ** 3
            self._pos = start + (target - start) * f
            self._draw()
            if i < self.STEPS and self.winfo_exists():
                self._job = self.after(16, step, i + 1)

        step()

    def _draw(self):
        w, h = self._cw, self._ch
        seg = w / len(self.options)
        pad = s(3)

        if HAVE_PIL:
            self._blit(panel_image(
                w, h, s(11), fill=FIELD, fill_bottom=mix(FIELD, "#000000", 0.4),
                bg=self._bg, border=LINE, border_top=mix(LINE, BG, 0.3),
                inset=0))
        else:
            self.delete("bg")
            round_rect(self, 0, 0, w - 1, h - 1, s(9), fill=FIELD,
                       outline=LINE, tags="bg")

        self.delete("thumb")
        x0 = self._pos * seg + pad
        x1 = x0 + seg - pad * 2
        if HAVE_PIL:
            thumb = panel_image(
                int(round(x1 - x0)), h - pad * 2, s(8),
                fill=ACCENT, fill_bottom=GRAD_B, bg=FIELD,
                border=mix(GRAD_B, "#000000", 0.3),
                border_top=mix(ACCENT, "#ffffff", 0.35),
                glow=ACCENT, glow_r=s(6), glow_alpha=95, inset=s(1))
            if thumb is not None:
                self._thumb_img = thumb
                self.create_image(x0, pad, image=thumb, anchor="nw",
                                  tags="thumb")
        else:
            gradient_rect(self, x0, pad, x1, h - pad, s(7), ACCENT, GRAD_B,
                          steps=6)

        self.delete("label")
        for i, opt in enumerate(self.options):
            active = abs(self._pos - i) < 0.5
            label = self.labels.get(opt, opt.title())
            if active:
                fill = "#ffffff"
            elif self._hover == i:
                fill = TEXT
            else:
                fill = MUTED
            self.create_text(i * seg + seg / 2, h / 2, text=label, fill=fill,
                             tags="label",
                             font=(FONT, 9, "bold" if active else "normal"))


class KeyCaps(_Painted):
    """Renders a shortcut as little keyboard caps, e.g.  Ctrl + Win."""

    def __init__(self, parent, keys, bg=CARD, height=38):
        self.keys = keys
        self._bg = bg
        self._caps = []
        super().__init__(parent, height=s(height), bg=bg,
                         highlightthickness=0, bd=0)
        self.bind("<Configure>", lambda _e: self._draw())

    def _draw(self):
        self.delete("all")
        self._caps = []
        x = s(2)
        h = s(30)
        y = (int(self["height"]) - h) / 2
        for i, key in enumerate(self.keys):
            f = tkfont.Font(family=FONT, size=10, weight="bold")
            w = f.measure(key) + s(24)
            if HAVE_PIL:
                cap = panel_image(
                    int(w), int(h), s(8),
                    fill=CARD_HI, fill_bottom=mix(CARD_HI, BG, 0.45),
                    bg=self._bg, border=mix(LINE, BG, 0.2),
                    border_top=LINE_HI, glow=GRAD_B, glow_r=s(5),
                    glow_alpha=40, inset=s(1))
                if cap is not None:
                    self._caps.append(cap)
                    self.create_image(x, y, image=cap, anchor="nw")
            else:
                round_rect(self, x, y, x + w, y + h, s(7),
                           fill=CARD_HI, outline=LINE)
            self.create_text(x + w / 2, y + h / 2 - 1, text=key, fill=TEXT,
                             font=(FONT, 10, "bold"))
            x += w
            if i < len(self.keys) - 1:
                self.create_text(x + s(10), y + h / 2, text="+", fill=MUTED,
                                 font=(FONT, 11))
                x += s(22)


class Wave(tk.Canvas):
    """Live level history, drawn as centred bars with rounded caps."""

    def __init__(self, parent, width=300, height=52, bars=34, bg=CARD):
        width, height = s(width), s(height)
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.bars = bars
        self.levels = [0.0] * bars
        self._cw, self._ch = width, height
        self._bg = bg
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
        self.delete("all")
        n = self.bars
        slot = self._cw / n
        # Cap the width so a wide window gives thin bars with air between them
        # rather than a row of fat lozenges.
        bw = max(2, min(slot * 0.42, s(3.5)))
        mid = self._ch / 2
        base = now_hue(0.0, 0.045)
        idle = mix(CARD, LINE_HI, 0.40)

        for i, lvl in enumerate(self.levels[-n:]):
            db = 20 * math.log10(max(lvl, 1e-6))
            frac = max(0.03, min(1.0, (db + 60) / 60))
            bh = max(2, frac * (self._ch - s(9)))
            x = slot * (i + 0.5)
            if self.active:
                colour = ribbon(base + (i / n) * 0.5)
                # A wider, dimmer pass underneath reads as bloom around the bar.
                self.create_line(x, mid - bh / 2, x, mid + bh / 2,
                                 fill=mix(self._bg, colour, 0.26),
                                 width=bw + s(2.5), capstyle="round")
                colour = mix(colour, "#ffffff", 0.08 + 0.22 * frac)
            else:
                colour = idle
            self.create_line(x, mid - bh / 2, x, mid + bh / 2,
                             fill=colour, width=bw, capstyle="round")


class Rule(_Painted):
    """A hairline that fades along the brand ribbon, for separating sections."""

    def __init__(self, parent, height=2, bg=BG, fade=True):
        super().__init__(parent, height=s(height), bg=bg,
                         highlightthickness=0, bd=0)
        self._bg = bg
        self._fade = fade
        self._item = None
        self._last = None
        self.bind("<Configure>", self._redraw)

    def _redraw(self, event):
        w, h = event.width, event.height
        if (w, h) == self._last or w < 4 or h < 1:
            return
        self._last = (w, h)
        if HAVE_PIL:
            self._blit(_cached(("rule", w, h, self._bg, self._fade),
                               lambda: self._build(w, h)))
        else:
            self.delete("all")
            self.create_line(0, h / 2, w, h / 2, fill=LINE)

    def _build(self, w, h):
        img = _hgradient((w, h), (ACCENT, GRAD_B, ACCENT_2))
        if self._fade:
            # Fading both ends into the page stops it looking like a border.
            mask = Image.new("L", (w, h), 0)
            px = mask.load()
            for x in range(w):
                t = x / max(1, w - 1)
                a = min(1.0, min(t, 1 - t) * 5.0)
                for y in range(h):
                    px[x, y] = int(190 * a)
            base = Image.new("RGB", (w, h), _rgb(self._bg))
            base.paste(img, mask=mask)
            img = base
        return ImageTk.PhotoImage(img)


class Dot(tk.Canvas):
    """The little status light next to the state text, with a soft halo."""

    def __init__(self, parent, size=12, bg=CARD):
        px = s(size)
        super().__init__(parent, width=px, height=px, bg=bg,
                         highlightthickness=0, bd=0)
        self._px = px
        self._bg = bg
        self.set(MUTED)

    def set(self, colour):
        """Three concentric discs: a wide faint halo fading into a solid core."""
        self.delete("all")
        p = self._px
        c = p / 2
        for scale, strength in ((1.0, 0.20), (0.72, 0.48), (0.44, 1.0)):
            r = (p / 2) * scale
            fill = colour if strength == 1.0 else mix(self._bg, colour, strength)
            self.create_oval(c - r, c - r, c + r, c + r, fill=fill, outline="")
