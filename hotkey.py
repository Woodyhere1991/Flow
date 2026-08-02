r"""
Global push-to-talk dictation.

  Hold Ctrl+Win          -> records while held, transcribes when you let go
  Double-tap Ctrl+Win    -> starts recording hands-free
  Tap Ctrl+Win once      -> stops that recording and transcribes

The text is pasted wherever you are typing, and always copied to the clipboard
as a fallback.

PRIVACY: the microphone is held open the whole time this runs, so that
push-to-talk catches your first word instead of losing it to the ~0.65s a mic
takes to wake up. Audio sits in memory only - a rolling window of the last
MAX_BUFFER_SECONDS - and nothing is written to disk or sent anywhere. Closing
the window releases the mic.

Launch with Dictate.bat (or: venv\Scripts\pythonw.exe hotkey.py)
"""

import ctypes
import difflib
import json
import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import messagebox, ttk

import numpy as np
import sounddevice as sd
from pynput import keyboard

import ui
import wintext
from overlay import Overlay

APP_DATA_DIR = Path(os.environ.get(
    "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
)) / "Flow"
SETTINGS_PATH = APP_DATA_DIR / "settings.json"
HARDWARE_PATH = APP_DATA_DIR / "hardware.json"
LEGACY_SETTINGS_PATH = Path(__file__).with_name("settings.json")

RATE = 16000
MAX_BUFFER_SECONDS = 120     # rolling audio kept in memory
PREROLL_SECONDS = 0.35       # audio kept from just before the key went down
HOLD_THRESHOLD = 0.35        # longer than this = a hold, shorter = a tap
DOUBLE_TAP_WINDOW = 0.70     # forgiving enough for a deliberate double-tap
MIN_CLIP_SECONDS = 0.25
SILENCE_PEAK = 0.0002

# Whisper invents plausible sentences out of near-silence ("What was it like at
# home?" from an empty room), and in intended mode those look like real speech,
# so no text filter can catch them. Gate on loudness instead: a clip has to be
# meaningfully louder than the room before it is worth transcribing. The floor
# is absolute; the multiplier adapts to whatever this room's background is.
# Measured ambient on this mic sits around 0.0038 rms, so the floor has to
# clear that without rejecting genuinely quiet speech - speech runs several
# times louder than room noise even on a poor Bluetooth mic.
MIN_SPEECH_RMS = 0.005
SPEECH_OVER_AMBIENT = 1.8
AMBIENT_SMOOTHING = 0.05

IDLE, PTT, TOGGLE = "idle", "ptt", "toggle"

# CrisperWhisper transcribes verbatim, so an empty room still yields tokens like
# "[breath]" or "[lipsmack]". Typing those into a document would be worse than
# typing nothing, so a result made up entirely of them counts as silence.
# Note this only suppresses noise-ONLY results - markers mixed in with real
# speech are left alone, because in verbatim mode they are the point.
NOISE_ONLY = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|[\s.,!?-])*\s*$")


def apply_spoken_replacements(text, replacements):
    """Apply private, user-defined corrections after transcription."""
    if not isinstance(replacements, dict):
        return text

    # Longer phrases go first so a short nickname cannot take part of a more
    # specific phrase. Whitespace is flexible because speech models sometimes
    # insert extra spaces around dictated punctuation.
    items = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    for spoken, written in items:
        if not isinstance(spoken, str) or not isinstance(written, str):
            continue
        words = spoken.strip().split()
        if not words:
            continue
        phrase = r"\s+".join(re.escape(word) for word in words)
        text = re.sub(rf"(?<!\w){phrase}(?!\w)", written, text,
                      flags=re.IGNORECASE)
    return text


def extract_simple_correction(original, corrected):
    """Return one safe phrase replacement from a corrected transcript."""
    before = original.split()
    after = corrected.split()
    changes = [
        change for change in difflib.SequenceMatcher(None, before, after).get_opcodes()
        if change[0] != "equal"
    ]
    if len(changes) != 1:
        return None
    tag, old_start, old_end, new_start, new_end = changes[0]
    old_words = before[old_start:old_end]
    new_words = after[new_start:new_end]
    if tag != "replace" or not old_words or not new_words:
        return None
    if len(old_words) > 6 or len(new_words) > 6:
        return None
    return " ".join(old_words), " ".join(new_words)

# The model supports these natively; this is not post-processing.
#   verbatim - every word as spoken, including "um", stutters, [breath], [laugh]
#   intended - what you meant to say: fillers dropped, punctuation tidied
MODES = ("intended", "verbatim")
MODE_HELP = {
    "intended": "Recommended - removes ums and tidies punctuation.",
    "verbatim": "Word for word - keeps ums, pauses, and sounds.",
}

# Measured on this machine (RTX 4060), weights already cached:
#   turbo  load  8.2s | transcribe 1.1s
#   small  load  6.3s | transcribe 1.2s
#   large  load 17.2s | transcribe 3.8s
# turbo is the default: half the startup of large and ~3.4x faster per phrase,
# with no visible quality difference on dictation-length clips.
SIZES = ("turbo", "small", "large")
SIZE_HELP = {
    "turbo": "Fast and accurate when NVIDIA acceleration is available.",
    "small": "Fastest, but may make a few more mistakes.",
    "large": "Most accurate, but takes longer.",
}

STARTUP_DIR = Path(os.environ.get("APPDATA", "")) / \
    r"Microsoft\Windows\Start Menu\Programs\Startup"
STARTUP_LINK = STARTUP_DIR / "Flow Dictation.lnk"


class Dictation:
    def __init__(self, root):
        self.root = root
        root.title("Flow")
        self.scale = ui.scale_for_dpi(root)
        # This display is 300% scaled, so the usable logical area is small -
        # ask for the ideal size but never exceed what the monitor can show.
        w, h = ui.fit_to_screen(root, ui.s(560), ui.s(600), margin=130)
        root.geometry(f"{w}x{h}")
        root.minsize(ui.s(500), min(ui.s(560), h))
        ui.dark_titlebar(root)

        self.events = queue.Queue()

        # rolling audio buffer -------------------------------------------------
        self.chunks = deque()
        self.total = 0        # absolute samples ever captured
        self.dropped = 0      # absolute samples discarded off the front
        self.lock = threading.Lock()
        self.stream = None
        self.mic_error = None
        self.next_mic_check = 0.0

        # hotkey state ---------------------------------------------------------
        self.ctrl = False
        self.win = False
        self.combo_since = None
        self.combo_armed = False
        self.last_tap = 0.0
        self.mode = IDLE
        self.mark = None

        self.model = None
        self.busy = False
        self.last_text = ""
        self.last_insert_hwnd = None
        self.last_insert_time = 0.0
        self.ambient = 0.0      # rolling estimate of room noise, learnt while idle
        self.target_hwnd = None  # window that was focused when dictation began
        self.personalize_window = None
        self.personalize_mark = None
        self.settings_window = None
        self.record_to_flow = False

        self.hardware_profile = self._load_hardware_profile()
        recommended = self.hardware_profile.get("recommended_model", "turbo")
        self.recommended_size = recommended if recommended in SIZES else "turbo"
        self.hardware_warning = self.hardware_profile.get("warning", "")

        saved = self._load_settings()
        saved_replacements = saved.get("spoken_replacements", {})
        self.spoken_replacements = (
            saved_replacements if isinstance(saved_replacements, dict) else {}
        )
        self.setup_seen = bool(saved.get("setup_seen", False))
        self.hardware_warning_seen = bool(
            saved.get("hardware_warning_seen", False))
        self.hardware_choice_confirmed = bool(
            saved.get("hardware_choice_confirmed", False))
        self.auto_paste = tk.BooleanVar(value=saved.get("auto_paste", True))
        self.text_mode = tk.StringVar(value=saved.get("mode", "intended"))
        self.show_overlay = tk.BooleanVar(value=saved.get("show_overlay", True))
        saved_size = saved.get("size", self.recommended_size)
        self.size = tk.StringVar(
            value=saved_size if saved_size in SIZES else self.recommended_size)
        self.at_startup = tk.BooleanVar(value=STARTUP_LINK.exists())
        for var in (self.auto_paste, self.text_mode, self.show_overlay, self.size):
            var.trace_add("write", lambda *_: self._save_settings())
        self.at_startup.trace_add("write", lambda *_: self._apply_startup())

        self.overlay = Overlay(root, on_cancel=self._cancel_recording)

        self._build_ui()
        self.root.after(80, self._drain)
        self.root.after(500, self._maybe_warn_hardware)
        self.root.after(1200, self._maybe_open_setup)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        threading.Thread(target=self._load_model, args=(self.size.get(),),
                         daemon=True).start()
        self._start_stream()
        self._start_hotkeys()

    # ---------------------------------------------------------------- UI ----
    def _build_ui(self):
        self.root.configure(bg=ui.BG)
        icon = Path(__file__).with_name("icon.ico")
        if icon.exists():
            ui.set_window_icon(self.root, icon)

        wrap = tk.Frame(self.root, bg=ui.BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=16)

        head = tk.Frame(wrap, bg=ui.BG)
        head.pack(fill="x")
        brand = tk.Frame(head, bg=ui.BG)
        brand.pack(side="left")
        tk.Label(brand, text="Flow", bg=ui.BG, fg=ui.TEXT,
                 font=(ui.FONT, 21, "bold"), anchor="w").pack(anchor="w")
        tk.Label(brand, text="Private voice typing", bg=ui.BG, fg=ui.MUTED,
                 font=(ui.FONT, 9), anchor="w").pack(anchor="w")
        hardware_text, hardware_colour = self._hardware_status()
        if hardware_text:
            tk.Label(brand, text=hardware_text, bg=ui.BG, fg=hardware_colour,
                     font=(ui.FONT, 8, "bold"), anchor="w").pack(anchor="w")
        head_actions = tk.Frame(head, bg=ui.BG)
        head_actions.pack(side="right", pady=(5, 0))
        ui.Button(head_actions, "Personalize", self._open_personalize,
                  width=120, bg=ui.BG).pack(side="left")
        ui.Button(head_actions, "Settings", self._open_settings,
                  width=95, bg=ui.BG).pack(side="left", padx=(8, 0))

        live = ui.Card(wrap)
        live.pack(fill="x", pady=(16, 12))
        tk.Label(live.body, text="SPEAK HERE", bg=ui.CARD, fg=ui.ACCENT_2,
                 font=(ui.FONT, 8, "bold"), anchor="w").pack(
                     fill="x", padx=18, pady=(15, 3))
        tk.Label(live.body, text="Turn your voice into text", bg=ui.CARD,
                 fg=ui.TEXT, font=(ui.FONT, 15, "bold"), anchor="w").pack(
                     fill="x", padx=18)
        tk.Label(
            live.body,
            text="Click Start talking, speak naturally, then click Stop.",
            bg=ui.CARD, fg=ui.MUTED, font=(ui.FONT, 9), anchor="w",
        ).pack(fill="x", padx=18, pady=(3, 10))

        self.talk_button = ui.Button(
            live.body, "Start talking", self._toggle_main_recording,
            primary=True, width=220, height=46,
        )
        self.talk_button.pack(anchor="w", padx=18)

        status = tk.Frame(live.body, bg=ui.CARD)
        status.pack(fill="x", padx=18, pady=(10, 0))
        self.status_dot = tk.Canvas(status, width=10, height=10, bg=ui.CARD,
                                    highlightthickness=0)
        self.status_dot.pack(side="left", pady=(4, 0))
        self.state_lbl = tk.Label(status, text="Starting Flow...", bg=ui.CARD,
                                  fg=ui.MUTED, font=(ui.FONT, 9), anchor="w")
        self.state_lbl.pack(side="left", padx=8, fill="x", expand=True)

        self.wave = ui.Wave(live.body, height=28)
        self.wave.pack(fill="x", padx=18, pady=(4, 9))

        anywhere = ui.Card(wrap)
        anywhere.pack(fill="x", pady=(0, 12))
        tk.Label(anywhere.body, text="TYPE INTO ANY APP", bg=ui.CARD,
                 fg=ui.MUTED, font=(ui.FONT, 8, "bold"), anchor="w").pack(
                     fill="x", padx=18, pady=(13, 3))
        tk.Label(
            anywhere.body,
            text="1. Click where you want the words to appear.\n"
                 "2. Hold the Ctrl and Windows keys while you speak.\n"
                 "3. Let go when you are finished.",
            bg=ui.CARD, fg=ui.TEXT, font=(ui.FONT, 9), anchor="w",
            justify="left",
        ).pack(fill="x", padx=18)
        keys = ui.KeyCaps(anywhere.body, ["Ctrl", "Windows"], height=34)
        keys.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(
            anywhere.body,
            text="Hands-free: tap these keys twice. Tap once to stop.",
            bg=ui.CARD, fg=ui.ACCENT_2, font=(ui.FONT, 8, "bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 9))

        tk.Label(wrap, text="YOUR LATEST TEXT", bg=ui.BG, fg=ui.MUTED,
                 font=(ui.FONT, 8, "bold"), anchor="w").pack(
                     fill="x", pady=(4, 6))

        box = ui.Card(wrap)
        box.pack(fill="both", expand=True)
        self.out = tk.Text(
            box.body, wrap="word", font=(ui.FONT, 10), bg=ui.CARD,
            fg=ui.TEXT, relief="flat", insertbackground=ui.CARD, height=2,
            takefocus=0, state="disabled", cursor="arrow", padx=12,
            pady=10, highlightthickness=0,
        )
        self.out.pack(fill="both", expand=True)
        self.out.config(state="normal")
        self.out.insert("1.0", "Your words will appear here.")
        self.out.config(state="disabled")

        row = tk.Frame(wrap, bg=ui.BG)
        row.pack(fill="x", pady=(10, 0))
        ui.Button(row, "Copy text", self._copy_last, primary=True,
                  width=115, bg=ui.BG).pack(side="left")
        ui.Button(row, "Fix text", self._correct_last,
                  width=100, bg=ui.BG).pack(side="left", padx=8)
        ui.Button(row, "Undo typing", self._undo_last,
                  width=110, bg=ui.BG).pack(side="left")

        # Kept so existing code that writes to self.meter keeps working.
        self.meter = tk.Label(wrap, bg=ui.BG, fg=ui.BG, text="")

    def _switch_row(self, parent, label, var, description="", first=False):
        row = tk.Frame(parent, bg=ui.CARD)
        row.pack(fill="x", padx=16, pady=(13 if first else 9, 0))
        words = tk.Frame(row, bg=ui.CARD)
        words.pack(side="left", fill="x", expand=True)
        tk.Label(words, text=label, bg=ui.CARD, fg=ui.TEXT,
                 font=(ui.FONT, 9, "bold"), anchor="w").pack(fill="x")
        if description:
            tk.Label(words, text=description, bg=ui.CARD, fg=ui.MUTED,
                     font=(ui.FONT, 8), anchor="w", justify="left",
                     wraplength=ui.s(360)).pack(fill="x", pady=(2, 0))
        ui.Toggle(row, var).pack(side="right")

    def _open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self.settings_window = win
        win.title("Flow settings")
        win.configure(bg=ui.BG)
        win.geometry(f"{ui.s(500)}x{ui.s(460)}")
        win.minsize(ui.s(460), ui.s(430))
        win.transient(self.root)
        ui.dark_titlebar(win)
        icon = Path(__file__).with_name("icon.ico")
        if icon.exists():
            ui.set_window_icon(win, icon)

        wrap = tk.Frame(win, bg=ui.BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(wrap, text="Settings", bg=ui.BG, fg=ui.TEXT,
                 font=(ui.FONT, 18, "bold"), anchor="w").pack(fill="x")
        tk.Label(
            wrap,
            text=self._settings_intro(),
            bg=ui.BG, fg=ui.MUTED, font=(ui.FONT, 9), anchor="w",
            wraplength=ui.s(450), justify="left",
        ).pack(fill="x", pady=(3, 14))

        writing = ui.Card(wrap)
        writing.pack(fill="x", pady=(0, 10))
        tk.Label(writing.body, text="HOW SHOULD FLOW WRITE?", bg=ui.CARD,
                 fg=ui.MUTED, font=(ui.FONT, 8, "bold"), anchor="w").pack(
                     fill="x", padx=16, pady=(13, 6))
        self.seg = ui.Segmented(
            writing.body, MODES, self.text_mode, width=300,
            command=self._mode_changed,
            labels={"intended": "Clean", "verbatim": "Word for word"},
        )
        self.seg.pack(padx=14, anchor="w")
        self.mode_hint = tk.Label(
            writing.body, bg=ui.CARD, fg=ui.MUTED, font=(ui.FONT, 8),
            anchor="w", text=MODE_HELP[self.text_mode.get()],
        )
        self.mode_hint.pack(fill="x", padx=16, pady=(6, 11))

        accuracy = ui.Card(wrap)
        accuracy.pack(fill="x", pady=(0, 10))
        tk.Label(accuracy.body, text="SPEED AND ACCURACY", bg=ui.CARD,
                 fg=ui.MUTED, font=(ui.FONT, 8, "bold"), anchor="w").pack(
                     fill="x", padx=16, pady=(13, 6))
        ui.Segmented(
            accuracy.body, SIZES, self.size, width=330,
            command=self._size_changed,
            labels={
                "turbo": (
                    "Recommended" if self.recommended_size == "turbo" else "Turbo"),
                "small": (
                    "Recommended" if self.recommended_size == "small" else "Fastest"),
                "large": "Most accurate",
            },
        ).pack(padx=14, anchor="w")
        self.size_hint = tk.Label(
            accuracy.body, bg=ui.CARD, fg=ui.MUTED, font=(ui.FONT, 8),
            anchor="w", text=self._size_help(self.size.get()),
        )
        self.size_hint.pack(fill="x", padx=16, pady=(6, 11))

        opts = ui.Card(wrap)
        opts.pack(fill="x", pady=(0, 10))
        self._switch_row(
            opts.body, "Type into the app I am using", self.auto_paste,
            "Used when you hold Ctrl and Windows to speak.", first=True)
        self._switch_row(
            opts.body, "Show the listening indicator", self.show_overlay,
            "Shows a small indicator while Flow is listening.")
        self._switch_row(
            opts.body, "Open Flow when Windows starts", self.at_startup,
            "Flow will be ready whenever you sign in.")

        ui.Button(wrap, "Done", self._close_settings, primary=True,
                  width=100, bg=ui.BG).pack(anchor="w", pady=(2, 0))
        win.protocol("WM_DELETE_WINDOW", self._close_settings)

    def _close_settings(self):
        if self.settings_window:
            self.settings_window.destroy()
        self.settings_window = None

    def _mode_changed(self):
        self.mode_hint.config(text=MODE_HELP[self.text_mode.get()])

    def _size_changed(self):
        self.hardware_choice_confirmed = True
        self._save_settings()
        self.size_hint.config(text=self._size_help(self.size.get()))
        if getattr(self, "loaded_size", None) == self.size.get():
            return
        # Swap models in the background so the UI stays responsive.
        self.model = None
        self._set_state("Switching model...", ui.WARN)
        threading.Thread(target=self._load_model, args=(self.size.get(),),
                         daemon=True).start()

    def _show_transcript(self, text):
        """Write into the read-only transcript box."""
        self.out.config(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)
        self.out.config(state="disabled")

    def _clear(self):
        self._show_transcript("")
        self.last_text = ""

    def _load_settings(self):
        # Older versions kept personal phrases beside the source code. This
        # project lives in OneDrive, so move that private file into the current
        # Windows user's local app-data folder the first time this version runs.
        try:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            if LEGACY_SETTINGS_PATH.exists():
                if SETTINGS_PATH.exists():
                    legacy = json.loads(
                        LEGACY_SETTINGS_PATH.read_text(encoding="utf-8"))
                    current = json.loads(
                        SETTINGS_PATH.read_text(encoding="utf-8"))
                    merged = {**legacy, **current}
                    old_words = legacy.get("spoken_replacements", {})
                    new_words = current.get("spoken_replacements", {})
                    if isinstance(old_words, dict) and isinstance(new_words, dict):
                        merged["spoken_replacements"] = {**old_words, **new_words}
                    SETTINGS_PATH.write_text(
                        json.dumps(merged, indent=2), encoding="utf-8")
                    LEGACY_SETTINGS_PATH.unlink()
                else:
                    LEGACY_SETTINGS_PATH.replace(SETTINGS_PATH)
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            try:
                return json.loads(
                    LEGACY_SETTINGS_PATH.read_text(encoding="utf-8"))
            except Exception:
                return {}

    def _load_hardware_profile(self):
        try:
            profile = json.loads(HARDWARE_PATH.read_text(encoding="utf-8"))
            return profile if isinstance(profile, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _hardware_status(self):
        performance = self.hardware_profile.get("performance")
        if performance == "fast":
            return "NVIDIA acceleration - fast mode", ui.GOOD
        if performance == "constrained_gpu":
            return "NVIDIA acceleration - Small model for limited memory", ui.WARN
        if performance == "possibly_unusable":
            return "CPU mode - Flow may not be useful", ui.REC
        if performance == "slow":
            return "CPU mode - transcription may be slow", ui.WARN
        return "", ui.MUTED

    def _settings_intro(self):
        status, _colour = self._hardware_status()
        if status:
            return f"{status}. Flow recommends the {self.recommended_size} model."
        return "Flow is already set up. Change these only if you want to."

    def _size_help(self, size):
        if size == self.recommended_size:
            return f"Recommended for this computer. {SIZE_HELP[size]}"
        if self.hardware_profile.get("device") == "cpu":
            if size == "large":
                return (
                    "May be impractically slow without NVIDIA acceleration. "
                    "It may need internet once to download.")
            if size == "turbo":
                return (
                    "More demanding than Small and likely slower on this CPU. "
                    "It may need internet once to download.")
        return f"{SIZE_HELP[size]} It may need internet once to download."

    def _maybe_warn_hardware(self):
        if not self.hardware_warning or self.hardware_warning_seen:
            return
        self.hardware_warning_seen = True
        self._save_settings()
        messagebox.showwarning(
            "Flow performance warning", self.hardware_warning, parent=self.root)

    def _save_settings(self):
        try:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps({
                "auto_paste": self.auto_paste.get(),
                "mode": self.text_mode.get(),
                "show_overlay": self.show_overlay.get(),
                "size": self.size.get(),
                "spoken_replacements": self.spoken_replacements,
                "setup_seen": self.setup_seen,
                "hardware_warning_seen": self.hardware_warning_seen,
                "hardware_choice_confirmed": self.hardware_choice_confirmed,
            }, indent=2), encoding="utf-8")
        except Exception:
            pass  # a settings write failing should never break dictation

    # -------------------------------------------------------- personalize ----
    def _maybe_open_setup(self):
        if not self.setup_seen:
            self._open_personalize(first_run=True)

    def _open_personalize(self, first_run=False):
        if self.personalize_window and self.personalize_window.winfo_exists():
            self.personalize_window.lift()
            self.personalize_window.focus_force()
            return

        self.setup_seen = True
        self._save_settings()

        win = tk.Toplevel(self.root)
        self.personalize_window = win
        win.title("Welcome to Flow" if first_run else "Personalize Flow")
        win.configure(bg=ui.BG)
        w, h = ui.fit_to_screen(win, ui.s(540), ui.s(700), margin=100)
        win.geometry(f"{w}x{h}")
        win.minsize(min(ui.s(490), w), min(ui.s(640), h))
        win.transient(self.root)
        ui.dark_titlebar(win)
        icon = Path(__file__).with_name("icon.ico")
        if icon.exists():
            ui.set_window_icon(win, icon)

        wrap = tk.Frame(win, bg=ui.BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=16)
        heading = "Welcome to Flow" if first_run else "Personalize Flow"
        intro = (
            "Two quick, optional steps help Flow understand you. "
            "You can change these later."
            if first_run else
            "Check your microphone and let Flow learn from your corrections."
        )
        tk.Label(wrap, text=heading, bg=ui.BG, fg=ui.TEXT,
                 font=(ui.FONT, 18, "bold"), anchor="w").pack(fill="x")
        tk.Label(
            wrap,
            text=intro,
            bg=ui.BG, fg=ui.MUTED, font=(ui.FONT, 9), anchor="w",
            wraplength=ui.s(470), justify="left",
        ).pack(fill="x", pady=(3, 14))

        check = ui.Card(wrap)
        check.pack(fill="x", pady=(0, 12))
        tk.Label(check.body, text="1. CHECK YOUR MICROPHONE", bg=ui.CARD,
                 fg=ui.ACCENT_2,
                 font=(ui.FONT, 8, "bold"), anchor="w").pack(
                     fill="x", padx=14, pady=(12, 5))
        tk.Label(check.body,
                 text="Click Start, read this sentence aloud, then click Stop:",
                 bg=ui.CARD, fg=ui.MUTED, font=(ui.FONT, 8), anchor="w",
                 wraplength=ui.s(450), justify="left").pack(
                     fill="x", padx=14, pady=(0, 4))
        tk.Label(check.body,
                 text='"Flow turns my spoken ideas into clear writing."',
                 bg=ui.CARD, fg=ui.TEXT, font=(ui.FONT, 10, "bold"), anchor="w",
                 wraplength=ui.s(450), justify="left").pack(
                     fill="x", padx=14)
        self.personalize_status = tk.Label(
            check.body, text="This checks that your microphone is working.",
            bg=ui.CARD, fg=ui.MUTED, font=(ui.FONT, 8), anchor="w",
            wraplength=ui.s(440), justify="left",
        )
        self.personalize_status.pack(fill="x", padx=14, pady=(5, 8))
        self.voice_check_btn = tk.Button(
            check.body, text="Start voice check", command=self._toggle_voice_check,
            bg=ui.ACCENT, fg="white", activebackground="#8f72ff",
            activeforeground="white", relief="flat", bd=0,
            font=(ui.FONT, 9, "bold"), cursor="hand2", padx=12, pady=6,
        )
        self.voice_check_btn.pack(anchor="w", padx=14, pady=(0, 12))

        teach = ui.Card(wrap)
        teach.pack(fill="both", expand=True)
        tk.Label(teach.body, text="2. LET FLOW LEARN AUTOMATICALLY",
                 bg=ui.CARD, fg=ui.ACCENT_2,
                 font=(ui.FONT, 8, "bold"), anchor="w").pack(
                     fill="x", padx=14, pady=(12, 3))
        tk.Label(
            teach.body,
            text=("After Flow gets something wrong, fix the latest dictation once. "
                  "Flow remembers a simple spelling change for next time."),
            bg=ui.CARD, fg=ui.MUTED, font=(ui.FONT, 8), anchor="w",
            wraplength=ui.s(450), justify="left",
        ).pack(fill="x", padx=14, pady=(0, 7))
        ui.Button(
            teach.body, "Fix latest dictation", self._correct_from_personalize,
            primary=True, width=155,
        ).pack(anchor="w", padx=14, pady=(0, 4))
        latest_help = (
            "Ready to fix your latest dictation."
            if self.last_text else
            "Nothing to fix yet. Dictate normally, then come back here."
        )
        self.learn_status = tk.Label(
            teach.body, text=latest_help, bg=ui.CARD, fg=ui.MUTED,
            font=(ui.FONT, 8), anchor="w",
        )
        self.learn_status.pack(fill="x", padx=14, pady=(0, 9))

        tk.Frame(teach.body, bg=ui.LINE, height=1).pack(
            fill="x", padx=14, pady=(0, 9))
        tk.Label(teach.body, text="ADD A SPECIAL PHRASE MANUALLY (OPTIONAL)",
                 bg=ui.CARD, fg=ui.MUTED,
                 font=(ui.FONT, 8, "bold"), anchor="w").pack(
                     fill="x", padx=14, pady=(0, 5))
        tk.Label(teach.body, text="If Flow hears:", bg=ui.CARD, fg=ui.TEXT,
                 font=(ui.FONT, 8), anchor="w").pack(fill="x", padx=14)
        self.heard_entry = tk.Entry(
            teach.body, bg="#101014", fg=ui.TEXT, insertbackground=ui.TEXT,
            relief="flat", font=(ui.FONT, 9),
        )
        self.heard_entry.pack(fill="x", padx=14, pady=(3, 7), ipady=5)
        tk.Label(teach.body, text="It should type:", bg=ui.CARD, fg=ui.TEXT,
                 font=(ui.FONT, 8), anchor="w").pack(fill="x", padx=14)
        self.written_entry = tk.Entry(
            teach.body, bg="#101014", fg=ui.TEXT, insertbackground=ui.TEXT,
            relief="flat", font=(ui.FONT, 9),
        )
        self.written_entry.pack(fill="x", padx=14, pady=(3, 7), ipady=5)
        self.phrase_status = tk.Label(
            teach.body, text="Example: my email  →  me@gmail.com",
            bg=ui.CARD, fg=ui.MUTED, font=(ui.FONT, 8), anchor="w",
        )
        self.phrase_status.pack(fill="x", padx=14)

        phrase_actions = tk.Frame(teach.body, bg=ui.CARD)
        phrase_actions.pack(fill="x", padx=14, pady=(7, 7))
        ui.Button(phrase_actions, "Save word", self._save_personal_phrase,
                  primary=True, width=110).pack(side="left")
        ui.Button(phrase_actions, "Remove selected", self._remove_personal_phrase,
                  width=140).pack(side="left", padx=8)

        self.phrase_list = tk.Listbox(
            teach.body, bg="#101014", fg=ui.TEXT, selectbackground=ui.ACCENT,
            selectforeground="white", relief="flat", bd=0,
            font=(ui.FONT, 8), height=5, activestyle="none",
        )
        self.phrase_list.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self._refresh_personal_phrases()

        ui.Button(wrap, "Done", self._close_personalize, primary=True,
                  width=100, bg=ui.BG).pack(anchor="w", pady=(10, 0))

        win.protocol("WM_DELETE_WINDOW", self._close_personalize)

    def _close_personalize(self):
        self.personalize_mark = None
        if self.personalize_window:
            self.personalize_window.destroy()
        self.personalize_window = None

    def _refresh_personal_phrases(self):
        if (not hasattr(self, "phrase_list")
                or not self.phrase_list.winfo_exists()):
            return
        self.phrase_list.delete(0, "end")
        for spoken, written in sorted(self.spoken_replacements.items()):
            self.phrase_list.insert("end", f"{spoken}  ->  {written}")

    def _correct_from_personalize(self):
        """Open the normal one-step correction flow from Personalize."""
        if not self.last_text:
            self.learn_status.config(
                text="Dictate something first, then click this button.",
                fg=ui.WARN,
            )
            return
        self._correct_last()

    def _save_personal_phrase(self):
        spoken = self.heard_entry.get().strip()
        written = self.written_entry.get().strip()
        if not spoken or not written:
            self.phrase_status.config(
                text="Fill in both boxes first.", fg=ui.WARN)
            return
        self.spoken_replacements[spoken] = written
        self._save_settings()
        self._refresh_personal_phrases()
        self.heard_entry.delete(0, "end")
        self.written_entry.delete(0, "end")
        self.phrase_status.config(text="Saved. Flow will use it next time.",
                                  fg=ui.GOOD)

    def _remove_personal_phrase(self):
        selected = self.phrase_list.curselection()
        if not selected:
            self.phrase_status.config(
                text="Click a saved phrase first.", fg=ui.WARN)
            return
        spoken = sorted(self.spoken_replacements)[selected[0]]
        self.spoken_replacements.pop(spoken, None)
        self._save_settings()
        self._refresh_personal_phrases()
        self.phrase_status.config(text="Removed.", fg=ui.MUTED)

    def _toggle_voice_check(self):
        if self.personalize_mark is None:
            if not self._ensure_microphone():
                self.personalize_status.config(
                    text="No microphone connected. Connect one and try again.",
                    fg=ui.REC)
                return
            if self.model is None:
                self.personalize_status.config(
                    text="Flow is still starting. Try again in a few seconds.",
                    fg=ui.WARN)
                return
            with self.lock:
                self.personalize_mark = self.total
            self.voice_check_btn.config(text="Stop voice check", bg=ui.REC)
            self.personalize_status.config(
                text="Listening... read the sentence, then click Stop.",
                fg=ui.TEXT)
            return

        mark, self.personalize_mark = self.personalize_mark, None
        audio = self._grab(mark)
        self.voice_check_btn.config(text="Start voice check", bg=ui.ACCENT)
        if len(audio) / RATE < 0.5:
            self.personalize_status.config(
                text="That was too short. Try once more.", fg=ui.WARN)
            return
        self.personalize_status.config(text="Checking...", fg=ui.WARN)
        threading.Thread(target=self._transcribe_voice_check,
                         args=(audio,), daemon=True).start()

    def _transcribe_voice_check(self, audio):
        import tempfile
        import soundfile as sf
        tmp = Path(tempfile.gettempdir()) / "flow_voice_check.wav"
        try:
            sf.write(str(tmp), audio, RATE)
            result = self.model.transcribe(str(tmp), language="en",
                                           mode="intended")
            self.events.put(("voice_check", result.text.strip()))
        except Exception as exc:
            self.events.put(("voice_check_error", str(exc)))
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _show_voice_check_result(self, text):
        if not self.personalize_window or not self.personalize_window.winfo_exists():
            return
        expected = "flow turns my spoken ideas into clear writing"
        heard = " ".join(re.findall(r"[a-z0-9]+", text.lower()))
        score = difflib.SequenceMatcher(None, expected, heard).ratio()
        if score >= 0.82:
            message, colour = "Good - Flow heard you clearly.", ui.GOOD
        else:
            message = f'Flow heard: "{text}"  You can try again or teach a word below.'
            colour = ui.WARN
        self.personalize_status.config(text=message, fg=colour)

    def _apply_startup(self):
        """Add or remove the Startup-folder shortcut."""
        try:
            if self.at_startup.get():
                pyw = Path(__file__).parent / "venv" / "Scripts" / "pythonw.exe"
                target = Path(__file__)
                icon = Path(__file__).with_name("icon.ico")
                ps = (
                    "$s=(New-Object -ComObject WScript.Shell)."
                    f"CreateShortcut('{STARTUP_LINK}');"
                    f"$s.TargetPath='{pyw}';"
                    f"$s.Arguments='\"{target}\"';"
                    f"$s.WorkingDirectory='{target.parent}';"
                    f"$s.IconLocation='{icon}';"
                    "$s.Save()"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, timeout=20,
                               creationflags=0x08000000)  # no console flash
                self._set_state("Will start with Windows", ui.GOOD)
            else:
                STARTUP_LINK.unlink(missing_ok=True)
                self._set_state("Removed from startup", ui.MUTED)
        except Exception as exc:
            self._set_state(f"Startup change failed: {exc}", ui.WARN)

    def _toggle_main_recording(self):
        """Start or stop the beginner-friendly recording on the main screen."""
        if self.busy:
            self._set_state("Flow is turning your speech into text...", ui.WARN)
            return
        if not self._ensure_microphone():
            return
        if self.model is None:
            self._set_state("Flow is still starting. Try again in a moment.", ui.WARN)
            return

        if self.mode == TOGGLE and self.record_to_flow:
            self._finish()
            return
        if self.mode != IDLE:
            self._set_state("Finish the current recording first.", ui.WARN)
            return

        with self.lock:
            self.mark = max(self.dropped,
                            self.total - int(PREROLL_SECONDS * RATE))
        self.record_to_flow = True
        self.mode = TOGGLE
        self.talk_button.set_text("Stop and write")
        self._set_state("Listening - speak now", ui.REC)
        if self.show_overlay.get():
            self.overlay.show_listening()

    def _reset_main_recording(self):
        self.record_to_flow = False
        if hasattr(self, "talk_button"):
            self.talk_button.set_text("Start talking")

    def _cancel_recording(self):
        """Throw away the in-flight recording (right-click the pill)."""
        if self.mode in (PTT, TOGGLE):
            self.mode = IDLE
            self.mark = None
            self._reset_main_recording()
            self._set_state("Cancelled", "#c80")
            self.overlay.show_done("Cancelled", good=False)

    def _set_state(self, text, colour=None):
        # Old call sites pass hex colours; map them onto the dark palette.
        mapped = {
            "#080": ui.GOOD, "#c80": ui.WARN, "#b00": ui.REC,
            "#666": ui.MUTED, None: ui.MUTED,
        }.get(colour, colour or ui.MUTED)
        self.state_lbl.config(text=text, fg=mapped)
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 9, 9, fill=mapped, outline=mapped)

    def _copy_last(self):
        if self.last_text:
            wintext.set_clipboard_text(self.last_text)
            self._set_state("Copied to clipboard", "#080")

    def _undo_last(self):
        if (not self.last_insert_hwnd
                or time.perf_counter() - self.last_insert_time > 30):
            self._set_state("Undo works for 30 seconds after dictation", "#c80")
            return
        if wintext.undo_in_window(self.last_insert_hwnd):
            self.last_insert_hwnd = None
            self.last_insert_time = 0.0
            self._set_state("Undid the last dictation", "#080")
            self.overlay.show_done("Undone")
        else:
            self._set_state("Couldn't return to the typing window", "#c80")

    def _correct_last(self):
        if not self.last_text:
            self._set_state("There is no dictation to correct yet", "#c80")
            return

        original = self.last_text
        win = tk.Toplevel(self.root)
        win.title("Correct last dictation")
        win.configure(bg=ui.BG)
        win.geometry(f"{ui.s(520)}x{ui.s(360)}")
        win.transient(self.root)
        ui.dark_titlebar(win)
        icon = Path(__file__).with_name("icon.ico")
        if icon.exists():
            ui.set_window_icon(win, icon)

        wrap = tk.Frame(win, bg=ui.BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(wrap, text="Correct last dictation", bg=ui.BG, fg=ui.TEXT,
                 font=(ui.FONT, 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(
            wrap,
            text="Fix the text below. Flow remembers a simple spelling change.",
            bg=ui.BG, fg=ui.MUTED, font=(ui.FONT, 9), anchor="w",
        ).pack(fill="x", pady=(3, 10))
        editor = tk.Text(
            wrap, wrap="word", bg=ui.CARD, fg=ui.TEXT,
            insertbackground=ui.TEXT, relief="flat", bd=0,
            font=(ui.FONT, 10), padx=12, pady=10, height=7,
        )
        editor.pack(fill="both", expand=True)
        editor.insert("1.0", original)
        editor.focus_set()

        actions = tk.Frame(wrap, bg=ui.BG)
        actions.pack(fill="x", pady=(10, 0))

        def save():
            corrected = " ".join(editor.get("1.0", "end").split())
            if not corrected:
                self._set_state("Correction was empty - nothing changed", "#c80")
                return

            learned = extract_simple_correction(original, corrected)
            if learned:
                self.spoken_replacements[learned[0]] = learned[1]
                self._save_settings()
                self._refresh_personal_phrases()

            replaced = False
            target = self.last_insert_hwnd
            recent = (target is not None
                      and time.perf_counter() - self.last_insert_time <= 30)
            if recent and wintext.undo_in_window(target):
                ok, _method = wintext.insert_text(corrected, target_hwnd=target)
                if ok:
                    replaced = True
                    self.last_insert_hwnd = target
                    self.last_insert_time = time.perf_counter()

            self.last_text = corrected
            self._show_transcript(corrected)
            wintext.set_clipboard_text(corrected)
            win.destroy()

            if learned:
                message = f'Remembered: "{learned[0]}" -> "{learned[1]}"'
                if (hasattr(self, "learn_status")
                        and self.learn_status.winfo_exists()):
                    self.learn_status.config(
                        text=(f'Learned "{learned[0]}" -> '
                              f'"{learned[1]}".'),
                        fg=ui.GOOD,
                    )
            elif replaced:
                message = "Corrected the last dictation"
            else:
                message = "Correction copied - paste it where needed"
            self._set_state(message, "#080")

        ui.Button(actions, "Save correction", save, primary=True,
                  width=125, bg=ui.BG).pack(side="left")
        ui.Button(actions, "Cancel", win.destroy,
                  width=85, bg=ui.BG).pack(side="left", padx=8)

    # -------------------------------------------------------------- model ----
    def _load_model(self, size):
        # size is passed in, never read from the Tk variable here: Tk variables
        # may only be touched from the thread running the main loop.
        try:
            import torch
            from crisperwhisper import CrisperWhisperModel
            profile_device = self.hardware_profile.get("device")
            use_cuda = torch.cuda.is_available() and profile_device != "cpu"
            device = "cuda" if use_cuda else "cpu"
            where = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
            self.events.put(("state", (f"Loading {size} on {where}...", "#c80")))
            # backend="transformers" is required on Windows - see README.
            self.model = CrisperWhisperModel(size, device=device,
                                             backend="transformers")
            self.loaded_size = size
            if self._microphone_active():
                self.events.put(("state", ("Ready to listen", "#080")))
            else:
                self.events.put(("state", ("No microphone connected", "#b00")))
        except Exception as exc:
            self.events.put(("state", (f"Model failed: {exc}", "#b00")))

    # -------------------------------------------------------------- audio ----
    def _start_stream(self):
        def cb(indata, _f, _t, _s):
            with self.lock:
                self.chunks.append(indata.copy().reshape(-1))
                self.total += len(indata)
                limit = MAX_BUFFER_SECONDS * RATE
                while self.total - self.dropped > limit and self.chunks:
                    self.dropped += len(self.chunks.popleft())

        try:
            if self._microphone_active():
                return True
            self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                         callback=cb, latency="low")
            self.stream.start()
            self.mic_error = None
            return True
        except Exception as exc:
            self.stream = None
            self.mic_error = str(exc)
            self.events.put(("state", ("No microphone connected", "#b00")))
            return False

    def _input_device_connected(self):
        """Return whether Windows currently has a usable default microphone."""
        try:
            device = sd.query_devices(kind="input")
            return int(device.get("max_input_channels", 0)) > 0
        except Exception:
            return False

    def _microphone_active(self):
        try:
            return bool(self.stream is not None and self.stream.active)
        except Exception:
            return False

    def _ensure_microphone(self):
        """Reconnect the mic if possible, otherwise explain the problem."""
        if not self._input_device_connected():
            self.mic_error = "No default input device"
            self._set_state(
                "No microphone connected - connect one and try again", ui.REC)
            self.overlay.show_done("No microphone connected", good=False)
            return False

        if self._microphone_active() or self._start_stream():
            self.mic_error = None
            return True

        self._set_state(
            "No microphone connected - connect one and try again", ui.REC)
        self.overlay.show_done("No microphone connected", good=False)
        return False

    def _watch_microphone(self):
        """Notice a headset being connected after Flow has already started."""
        now = time.perf_counter()
        if now < self.next_mic_check:
            return
        self.next_mic_check = now + 2.0

        connected = self._input_device_connected()
        active = self._microphone_active()
        if connected and not active:
            if self._start_stream() and self.model is not None and self.mode == IDLE:
                self._set_state("Microphone connected - ready to listen", ui.GOOD)
        elif not connected and active:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            if self.mode == IDLE:
                self._set_state("No microphone connected", ui.REC)

    def _grab(self, start_abs):
        """Audio from absolute sample index start_abs to now."""
        with self.lock:
            if not self.chunks:
                return np.zeros(0, dtype="float32")
            data = np.concatenate(list(self.chunks))
            begin = max(0, start_abs - self.dropped)
            return data[begin:].copy()

    def _recent_rms(self):
        """RMS over the last few chunks - used to learn the room's noise floor."""
        with self.lock:
            recent = list(self.chunks)[-5:]
        if not recent:
            return 0.0
        data = np.concatenate(recent)
        return float(np.sqrt((data ** 2).mean()))

    def _level(self):
        with self.lock:
            if not self.chunks:
                return 0.0
            recent = list(self.chunks)[-5:]
        return max(float(np.abs(c).max()) for c in recent) if recent else 0.0

    # ------------------------------------------------------------ hotkeys ----
    def _start_hotkeys(self):
        def on_press(key):
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                self.ctrl = True
            elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
                self.win = True
            else:
                return
            if self.ctrl and self.win and self.combo_since is None:
                self.combo_since = time.perf_counter()
                self.events.put(("combo_down", None))

        def on_release(key):
            was = self.ctrl and self.win
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                self.ctrl = False
            elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
                self.win = False
            else:
                return
            if was and not (self.ctrl and self.win):
                held = time.perf_counter() - (self.combo_since or time.perf_counter())
                self.combo_since = None
                self.events.put(("combo_up", held))

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.daemon = True
        self.listener.start()

    def _own_window(self, hwnd):
        """True if hwnd belongs to Flow itself (main window or the pill)."""
        if not hwnd:
            return True
        try:
            mine = {self.root.winfo_id(), self.overlay._hwnd}
            root_hwnd = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)
            if root_hwnd:
                mine.add(root_hwnd)
            return hwnd in mine
        except Exception:
            return False

    def _capture_target(self):
        """Remember where the user was typing when they started dictating.

        Without this the transcript gets pasted into whatever is focused when
        it finishes - which is Flow's own window if they glanced at it.
        """
        hwnd = wintext.get_foreground_window()
        if self._own_window(hwnd):
            return          # keep the previous target rather than targeting us
        self.target_hwnd = hwnd

    def _on_combo_down(self):
        if self.mode == TOGGLE:
            self.combo_armed = True
            return          # already recording hands-free; the tap-up stops it
        self.combo_armed = False
        if self.busy:
            return
        if not self._ensure_microphone():
            return
        if self.model is None:
            self._set_state("Flow is still starting. Try again in a moment.", ui.WARN)
            return
        self.combo_armed = True
        self._capture_target()
        # Start capturing immediately so a hold loses nothing. If this turns out
        # to be a short tap we simply throw the marker away.
        with self.lock:
            self.mark = max(self.dropped, self.total - int(PREROLL_SECONDS * RATE))
        self.mode = PTT
        self._set_state("Listening...", "#b00")
        if self.show_overlay.get():
            self.overlay.show_listening()

    def _on_combo_up(self, held):
        if not self.combo_armed:
            return
        self.combo_armed = False

        if self.mode == TOGGLE:
            # The next press always ends hands-free recording, even if the
            # user holds the keys slightly longer than a perfect tap.
            self._finish()
            return

        if self.mode == PTT and held >= HOLD_THRESHOLD:
            self._finish()
            return

        # Short tap while idle: could be the first half of a double-tap.
        self.mode = IDLE
        self.mark = None
        self._set_state("Ready to listen", "#080")

        now = time.perf_counter()
        if now - self.last_tap <= DOUBLE_TAP_WINDOW:
            self.last_tap = 0.0
            with self.lock:
                self.mark = self.total
            self.mode = TOGGLE
            self._set_state(
                "Hands-free listening is on - tap Ctrl+Windows to stop", "#b00")
            if self.show_overlay.get():
                self.overlay.show_listening()
        else:
            self.last_tap = now
            self.overlay.hide()

    def _finish(self):
        mark, self.mark = self.mark, None
        self.mode = IDLE
        if mark is None:
            self._reset_main_recording()
            return

        audio = self._grab(mark)
        secs = len(audio) / RATE
        if secs < MIN_CLIP_SECONDS:
            self._reset_main_recording()
            self._set_state("Too short - hold it a little longer", "#c80")
            self.overlay.show_done("Too short", good=False)
            return
        peak = float(np.abs(audio).max()) if len(audio) else 0.0
        if peak < SILENCE_PEAK:
            self._reset_main_recording()
            self._set_state("No sound picked up", "#c80")
            self.overlay.show_done("No sound", good=False)
            return

        rms = float(np.sqrt((audio ** 2).mean()))
        gate = max(MIN_SPEECH_RMS, self.ambient * SPEECH_OVER_AMBIENT)
        if rms < gate:
            self._reset_main_recording()
            self._set_state(
                f"Too quiet to be speech (rms {rms:.4f} < {gate:.4f})", "#c80")
            self.overlay.show_done("No speech detected", good=False)
            return

        self.busy = True
        if self.record_to_flow:
            self.talk_button.set_text("Writing...")
        self._set_state("Turning your speech into text...", "#c80")
        if self.show_overlay.get():
            self.overlay.show_transcribing()
        threading.Thread(target=self._transcribe,
                         args=(audio, self.text_mode.get()), daemon=True).start()

    def _transcribe(self, audio, mode):
        import tempfile

        import soundfile as sf
        tmp = Path(tempfile.gettempdir()) / "crisperwhisper_dictation.wav"
        try:
            sf.write(str(tmp), audio, RATE)
            # mode is a native model capability, not post-processing.
            result = self.model.transcribe(str(tmp), language="en", mode=mode)
            self.events.put(("text", result.text.strip()))
        except Exception as exc:
            self.events.put(("state", (f"Failed: {exc}", "#b00")))
            self.events.put(("done", None))
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------ dispatch ----
    def _deliver(self, text):
        main_recording = self.record_to_flow
        self._reset_main_recording()
        self.last_insert_hwnd = None
        self.last_insert_time = 0.0
        text = apply_spoken_replacements(text, self.spoken_replacements)
        self.last_text = text
        self._show_transcript(text)

        if not text or NOISE_ONLY.match(text):
            self._set_state("Nothing heard - nothing typed", "#c80")
            self.overlay.show_done("Nothing heard", good=False)
            return

        # Newlines are stripped deliberately: pasting a newline into a terminal
        # would submit the line as a command. Markers like [breath] are NOT
        # stripped - in verbatim mode they are exactly what was asked for, and
        # in intended mode the model has already left them out.
        flat = " ".join(text.split())

        if main_recording:
            wintext.set_clipboard_text(flat)
            words = len(flat.split())
            self._set_state(
                f"Done - {words} words are below and copied", "#080")
            self.overlay.show_done(f"Wrote {words} words")
            return

        if not self.auto_paste.get():
            wintext.set_clipboard_text(flat)
            self._set_state("Copied to clipboard", "#080")
            self.overlay.show_done("Copied")
            return

        ok, method = wintext.insert_text(flat, target_hwnd=self.target_hwnd)
        words = len(flat.split())
        if ok:
            self.last_insert_hwnd = self.target_hwnd
            self.last_insert_time = time.perf_counter()
            where = wintext.window_title(self.target_hwnd) or "the focused app"
            self._set_state(f"Typed {words} words into {where[:28]}", "#080")
            self.overlay.show_done(f"Typed {words} words")
        elif method == "lost-focus":
            self._set_state("Couldn't return to your window - copied instead", "#c80")
            self.overlay.show_done("Copied to clipboard", good=False)
        else:
            self._set_state("Couldn't type it - copied to clipboard instead", "#c80")
            self.overlay.show_done("Copied instead", good=False)

    def _drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "state":
                    self._set_state(*payload)
                elif kind == "combo_down":
                    self._on_combo_down()
                elif kind == "combo_up":
                    self._on_combo_up(payload)
                elif kind == "text":
                    self._deliver(payload)
                    self.busy = False
                elif kind == "voice_check":
                    self._show_voice_check_result(payload)
                elif kind == "voice_check_error":
                    if (self.personalize_window
                            and self.personalize_window.winfo_exists()):
                        self.personalize_status.config(
                            text=f"Voice check failed: {payload}", fg=ui.WARN)
                elif kind == "done":
                    self.busy = False
                    self._reset_main_recording()
        except queue.Empty:
            pass

        if self.mode == IDLE and not self.busy:
            self._watch_microphone()

        if self.mode in (PTT, TOGGLE):
            level = self._level()
            db = 20 * np.log10(max(level, 1e-6))
            filled = int(np.clip((db + 60) / 60 * 20, 0, 20))
            self.meter.config(text="█" * filled + "░" * (20 - filled))
            self.wave.active = True
            self.wave.push(level)
            self.wave.draw()
            self.overlay.push_level(level)
        else:
            self.meter.config(text="")
            if self.wave.active:
                self.wave.active = False
                self.wave.reset()
                self.wave.draw()
            # Learn the room's background level only while not recording, so
            # the gate adapts to a noisy room without counting speech as noise.
            quiet = self._recent_rms()
            if quiet > 0:
                self.ambient = (AMBIENT_SMOOTHING * quiet
                                + (1 - AMBIENT_SMOOTHING) * self.ambient)

        self.overlay.tick()
        self.root.after(80, self._drain)

    def _on_close(self):
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        try:
            self.listener.stop()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    ui.enable_dpi_awareness()      # must happen before the Tk root is created
    # Every Python script runs as "pythonw.exe" to Windows, so without this the
    # taskbar groups Flow under a generic Python icon instead of its own - the
    # pinned shortcut looks right (it points at an .ico directly) but the
    # running app's taskbar button doesn't, unless it gets a distinct identity.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Flow.Dictation")
    except Exception:
        pass
    root = tk.Tk()
    Dictation(root)
    root.mainloop()
