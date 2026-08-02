r"""
CrisperWhisper desktop app - record from the mic or pick a file, get a transcript.

Launch with Transcribe.bat (or: venv\Scripts\pythonw.exe app.py)
"""

import queue
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
import sounddevice as sd
import soundfile as sf

import ui

AUDIO_TYPES = [
    ("Audio files", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.aac *.mp4 *.mkv *.mov"),
    ("All files", "*.*"),
]

MODEL_HELP = {
    "large": "Most accurate, slowest",
    "medium": "Good balance",
    "small": "Faster, less accurate",
    "turbo": "Fastest",
}

LANGUAGES = ["auto", "en", "es", "fr", "de", "it", "pt", "nl", "pl",
             "ru", "ja", "ko", "zh", "ar", "hi", "tr"]

RECORD_RATE = 16000  # what Whisper wants; avoids a resample when the mic allows it

SILENCE_PEAK = 0.0002   # below this there is genuinely no signal at all
TEST_SECONDS = 5.0      # length of the "Test mic" check
WARMUP_TIMEOUT = 4.0    # how long to wait for the mic's first frame


def desktop_dir():
    """Best guess at the Desktop, accounting for OneDrive redirection."""
    for candidate in (
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "Desktop",
    ):
        if candidate.is_dir():
            return str(candidate)
    return str(Path.home())


def list_input_devices():
    """Return [(index, label)] for every device that can capture audio."""
    apis = sd.query_hostapis()
    found = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            api = apis[d["hostapi"]]["name"]
            name = d["name"].split("(@System32")[0].strip() or d["name"]
            found.append((i, f"{name[:40]} [{api}]"))
    return found


class App:
    def __init__(self, root):
        self.root = root
        root.title("CrisperWhisper - Speech to Text")
        root.geometry("860x640")
        root.minsize(700, 520)

        # Tkinter is not thread-safe: workers post here, the UI polls.
        self.events = queue.Queue()

        self.audio_path = None
        self.model = None            # cached so only the first run pays load time
        self.loaded_model_name = None
        self.busy = False
        self.recording = False
        self.testing = False
        self.rec_frames = []
        self.rec_stream = None
        self.rec_started = 0.0
        self.rec_rate = RECORD_RATE
        self.result_text = ""
        self.devices = []

        self._build_ui()
        self.refresh_devices()
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- UI ----
    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        # --- microphone -----------------------------------------------------
        mic = ttk.LabelFrame(self.root, text="Record from microphone")
        mic.pack(fill="x", **pad)

        mrow = ttk.Frame(mic)
        mrow.pack(fill="x", padx=10, pady=8)

        self.rec_btn = ttk.Button(mrow, text="Start recording", command=self.toggle_record)
        self.rec_btn.pack(side="left")
        ui.Tooltip(self.rec_btn, "Start recording from the selected microphone. Click again to stop.")

        self.test_btn = ttk.Button(mrow, text="Test mic", command=self.toggle_test)
        self.test_btn.pack(side="left", padx=6)
        ui.Tooltip(self.test_btn, "Listen briefly and show whether the selected microphone works.")

        self.rec_status = ttk.Label(mrow, text="", foreground="#666")
        self.rec_status.pack(side="left", padx=12)

        drow = ttk.Frame(mic)
        drow.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(drow, text="Mic:").pack(side="left")
        self.device_var = tk.StringVar()
        self.device_box = ttk.Combobox(drow, textvariable=self.device_var,
                                       state="readonly", width=48)
        self.device_box.pack(side="left", padx=6)
        ui.Tooltip(self.device_box, "Choose which connected microphone Flow should use.")
        refresh_btn = ttk.Button(drow, text="Refresh", command=self.refresh_devices)
        refresh_btn.pack(side="left")
        ui.Tooltip(refresh_btn, "Look again for microphones that were just connected.")

        # --- file -----------------------------------------------------------
        filef = ttk.LabelFrame(self.root, text="Or transcribe a file")
        filef.pack(fill="x", **pad)

        frow = ttk.Frame(filef)
        frow.pack(fill="x", padx=10, pady=8)

        self.pick_btn = ttk.Button(frow, text="Choose audio file...", command=self.pick_file)
        self.pick_btn.pack(side="left")
        ui.Tooltip(self.pick_btn, "Choose a saved audio or video file to turn into text.")

        self.file_label = ttk.Label(frow, text="No file selected", foreground="#666")
        self.file_label.pack(side="left", padx=12)

        # --- options --------------------------------------------------------
        opts = ttk.LabelFrame(self.root, text="Options")
        opts.pack(fill="x", **pad)

        row = ttk.Frame(opts)
        row.pack(fill="x", padx=10, pady=8)

        ttk.Label(row, text="Quality:").pack(side="left")
        self.model_var = tk.StringVar(value="large")
        box = ttk.Combobox(row, textvariable=self.model_var, values=list(MODEL_HELP),
                           state="readonly", width=9)
        box.pack(side="left", padx=(6, 4))
        box.bind("<<ComboboxSelected>>", self._update_model_hint)
        ui.Tooltip(box, "Choose a faster or more accurate speech model.")

        self.model_hint = ttk.Label(row, text=MODEL_HELP["large"], foreground="#666")
        self.model_hint.pack(side="left", padx=(0, 20))

        ttk.Label(row, text="Language:").pack(side="left")
        self.lang_var = tk.StringVar(value="en")
        language_box = ttk.Combobox(
            row, textvariable=self.lang_var, values=LANGUAGES,
            state="readonly", width=7,
        )
        language_box.pack(side="left", padx=6)
        ui.Tooltip(language_box, "Choose the language in the recording, or use auto to detect it.")

        self.ts_var = tk.BooleanVar(value=False)
        timings_btn = ttk.Checkbutton(
            row, text="Word timings", variable=self.ts_var,
        )
        timings_btn.pack(side="left", padx=20)
        ui.Tooltip(timings_btn, "Include the start and end time for each transcribed word.")

        # --- actions --------------------------------------------------------
        actions = ttk.Frame(self.root)
        actions.pack(fill="x", **pad)

        self.go_btn = ttk.Button(actions, text="Transcribe file",
                                 command=self.start_transcribe_file, state="disabled")
        self.go_btn.pack(side="left")
        ui.Tooltip(self.go_btn, "Turn the selected audio file into written text.")

        self.save_btn = ttk.Button(actions, text="Save as .txt",
                                   command=self.save_text, state="disabled")
        self.save_btn.pack(side="left", padx=8)
        ui.Tooltip(self.save_btn, "Save the finished transcription as a text file.")

        self.copy_btn = ttk.Button(actions, text="Copy", command=self.copy_text,
                                   state="disabled")
        self.copy_btn.pack(side="left")
        ui.Tooltip(self.copy_btn, "Copy the finished transcription so you can paste it elsewhere.")

        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=12)

        self.status = ttk.Label(self.root, text="Ready", foreground="#666")
        self.status.pack(fill="x", padx=12, pady=(4, 0), anchor="w")

        holder = ttk.Frame(self.root)
        holder.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        self.output = tk.Text(holder, wrap="word", font=("Consolas", 10), height=10)
        scroll = ttk.Scrollbar(holder, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        self.output.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _update_model_hint(self, _e=None):
        self.model_hint.config(text=MODEL_HELP[self.model_var.get()])

    # ------------------------------------------------------------ devices ----
    def refresh_devices(self):
        # PortAudio caches the device list at import; reinitialise so newly
        # connected mics (e.g. a Bluetooth headset) actually show up.
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass

        self.devices = list_input_devices()
        if self.devices:
            self.device_box.config(values=[label for _, label in self.devices])
            self.device_box.current(self._preferred_device_row())
            self.rec_btn.config(state="normal")
            self.test_btn.config(state="normal")
            self.rec_status.config(text="", foreground="#666")
        else:
            self.device_box.config(values=[])
            self.device_var.set("")
            self.rec_btn.config(state="disabled")
            self.test_btn.config(state="disabled")
            self.rec_status.config(text="No microphone found - see README", foreground="#b00")

    def _preferred_device_row(self):
        """Pick a real named mic over generic router entries, WASAPI first.

        Index 0 is usually "Microsoft Sound Mapper", which works but just
        forwards to whatever Windows treats as default - picking the actual
        device is more predictable, and WDM-KS is the flakiest backend.
        """
        generic = ("sound mapper", "primary sound capture")
        real = [
            row for row, (_, label) in enumerate(self.devices)
            if not any(g in label.lower() for g in generic)
        ]
        for api in ("WASAPI", "DirectSound", "MME"):
            for row in real:
                if api.lower() in self.devices[row][1].lower():
                    return row
        return real[0] if real else 0

    def _selected_device(self):
        label = self.device_var.get()
        for idx, lbl in self.devices:
            if lbl == label:
                return idx
        return None

    # ----------------------------------------------------------- recording ----
    def toggle_test(self):
        """Record a few seconds and report the level, without transcribing."""
        if self.testing:
            self.stop_test()
            return
        if self.recording or self.busy:
            return
        if not self._open_stream():
            return
        self.testing = True
        self.rec_started = time.perf_counter()
        self.test_btn.config(text="Stop test")
        self.rec_btn.config(state="disabled")
        self._tick_timer()

    def stop_test(self):
        self.testing = False
        self._close_stream()
        self.test_btn.config(text="Test mic")
        self.rec_btn.config(state="normal")

        if not self.rec_frames:
            self.rec_status.config(text="Test captured nothing", foreground="#b00")
            return

        audio = np.concatenate(self.rec_frames, axis=0)
        peak = float(np.abs(audio).max())
        rms = float(np.sqrt((audio ** 2).mean()))

        if peak < SILENCE_PEAK:
            verdict, colour = "NO SIGNAL - mic is muted or not capturing", "#b00"
        elif peak < 0.01:
            verdict, colour = "very quiet - raise mic volume in Windows", "#c80"
        elif peak < 0.1:
            verdict, colour = "quiet, but the app will boost it - should work", "#c80"
        else:
            verdict, colour = "good level", "#080"

        self.rec_status.config(
            text=f"Test: peak {peak:.4f}, rms {rms:.4f} - {verdict}", foreground=colour,
        )

    def toggle_record(self):
        if self.recording:
            self.stop_record()
        else:
            self.start_record()

    def _open_stream(self):
        """Open the mic and start filling self.rec_frames. False if it failed."""
        device = self._selected_device()
        if device is None:
            messagebox.showerror("No microphone", "No input device selected.")
            return False

        # Prefer 16 kHz, but fall back to whatever the device insists on.
        rate = RECORD_RATE
        try:
            sd.check_input_settings(device=device, samplerate=rate, channels=1)
        except Exception:
            try:
                rate = int(sd.query_devices(device)["default_samplerate"])
            except Exception:
                rate = 44100

        self.rec_frames = []
        self.rec_rate = rate

        def callback(indata, _frames, _t, status):
            if status:
                pass  # overflows are non-fatal; keep capturing
            self.rec_frames.append(indata.copy())

        try:
            self.rec_stream = sd.InputStream(
                device=device, samplerate=rate, channels=1,
                dtype="float32", callback=callback, latency="low",
            )
            self.rec_stream.start()
        except Exception as exc:
            self.rec_stream = None
            messagebox.showerror(
                "Could not open microphone",
                f"{type(exc).__name__}: {exc}\n\n"
                "If this is a Bluetooth headset, Windows must switch it to "
                "'Hands-Free' mode before the mic works. See README.md.",
            )
            return False

        # Opening a mic stream is not instant - WASAPI in particular can take
        # well over a second before the first frame arrives. Block until audio
        # is genuinely flowing, then throw away the warm-up frames, so the
        # user's first words aren't silently dropped.
        deadline = time.perf_counter() + WARMUP_TIMEOUT
        while not self.rec_frames and time.perf_counter() < deadline:
            self.root.update()
            time.sleep(0.02)

        if not self.rec_frames:
            self._close_stream()
            messagebox.showerror(
                "Microphone not responding",
                "The mic opened but never sent any audio.\n\n"
                "Try a different entry in the Mic dropdown, or hit Refresh.",
            )
            return False

        self.rec_frames = []  # discard warm-up; capture starts clean from here
        return True

    def _close_stream(self):
        try:
            if self.rec_stream:
                self.rec_stream.stop()
                self.rec_stream.close()
        except Exception:
            pass
        finally:
            self.rec_stream = None

    def start_record(self):
        if self.busy or self.testing:
            return
        self.rec_status.config(text="Starting mic...", foreground="#666")
        self.root.update_idletasks()
        if not self._open_stream():
            self.rec_status.config(text="", foreground="#666")
            return

        self.recording = True
        self.rec_started = time.perf_counter()
        self.rec_btn.config(text="Stop and transcribe")
        self.test_btn.config(state="disabled")
        self.pick_btn.config(state="disabled")
        self.go_btn.config(state="disabled")
        self._tick_timer()

    def _recent_level(self):
        """Peak over the last ~0.3s of captured audio."""
        if not self.rec_frames:
            return 0.0
        recent = self.rec_frames[-5:]
        return max(float(np.abs(f).max()) for f in recent)

    def _meter(self, level):
        """Log-scaled bar - a linear one is invisible at Bluetooth mic levels."""
        if level <= 0:
            return "", "#b00"
        db = 20 * np.log10(max(level, 1e-6))       # -120 dB .. 0 dB
        filled = int(np.clip((db + 60) / 60 * 20, 0, 20))  # -60 dB .. 0 dB
        bar = "█" * filled + "░" * (20 - filled)
        colour = "#b00" if filled < 3 else ("#c80" if filled < 7 else "#080")
        return f"{bar} {db:5.0f} dB", colour

    def _tick_timer(self):
        if not (self.recording or self.testing):
            return
        level = self._recent_level()
        bar, colour = self._meter(level)
        secs = time.perf_counter() - self.rec_started

        if self.testing:
            left = max(0.0, TEST_SECONDS - secs)
            self.rec_status.config(text=f"Testing... {left:0.1f}s  {bar}", foreground=colour)
            if left <= 0:
                self.stop_test()
                return
        else:
            self.rec_status.config(text=f"Recording {secs:0.1f}s  {bar}", foreground=colour)

        self.root.after(100, self._tick_timer)

    def stop_record(self):
        self.recording = False
        self._close_stream()

        self.rec_btn.config(text="Start recording")
        self.test_btn.config(state="normal")
        self.pick_btn.config(state="normal")

        if not self.rec_frames:
            self.rec_status.config(text="Nothing recorded", foreground="#b00")
            return

        audio = np.concatenate(self.rec_frames, axis=0)
        secs = len(audio) / self.rec_rate
        if secs < 0.3:
            self.rec_status.config(text="Too short - hold it a bit longer", foreground="#b00")
            return

        peak = float(np.abs(audio).max())
        if peak < SILENCE_PEAK:
            self.rec_status.config(
                text=f"No signal at all (peak {peak:.5f}) - check Windows mic volume",
                foreground="#b00",
            )
            return

        # Deliberately NOT normalising the level here. Whisper does its own
        # internal normalisation and transcribes quiet audio just as accurately;
        # boosting only amplifies room noise, which makes it hallucinate speech
        # out of near-silence (measured: a 9x boost turned ambient hiss into
        # "What's the weather in New Year's Eve?").
        tmp = Path(tempfile.gettempdir()) / "crisperwhisper_recording.wav"
        sf.write(str(tmp), audio, self.rec_rate)

        self.rec_status.config(text=f"Recorded {secs:0.1f}s (peak {peak:.3f})",
                               foreground="#666")
        self._launch(tmp)

    # -------------------------------------------------------------- files ----
    def pick_file(self):
        path = filedialog.askopenfilename(title="Choose an audio file", filetypes=AUDIO_TYPES)
        if not path:
            return
        self.audio_path = Path(path)
        self.file_label.config(text=self.audio_path.name, foreground="black")
        self.go_btn.config(state="normal")
        self._set_status(f"Ready to transcribe {self.audio_path.name}")

    def start_transcribe_file(self):
        if not self.audio_path:
            return
        if not self.audio_path.exists():
            messagebox.showerror("File missing", f"Can't find:\n{self.audio_path}")
            return
        self._launch(self.audio_path)

    # --------------------------------------------------------- transcribe ----
    def _launch(self, path):
        if self.busy:
            return
        self.busy = True
        self.result_text = ""
        self.go_btn.config(state="disabled")
        self.pick_btn.config(state="disabled")
        self.rec_btn.config(state="disabled")
        self.test_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.copy_btn.config(state="disabled")
        self.output.delete("1.0", "end")
        self.progress.start(12)

        threading.Thread(
            target=self._worker,
            args=(Path(path), self.model_var.get(), self.lang_var.get(), self.ts_var.get()),
            daemon=True,
        ).start()

    def _worker(self, path, model_name, language, timestamps):
        """Runs off the UI thread. Communicates only via self.events."""
        try:
            import torch
            from crisperwhisper import CrisperWhisperModel

            device = "cuda" if torch.cuda.is_available() else "cpu"

            if self.model is None or self.loaded_model_name != model_name:
                where = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
                self.events.put(("status",
                                 f"Loading {model_name} model on {where}... "
                                 "(first run takes a minute)"))
                # backend="transformers" is required on Windows - see README.
                self.model = CrisperWhisperModel(model_name, device=device,
                                                 backend="transformers")
                self.loaded_model_name = model_name

            self.events.put(("status", f"Transcribing {path.name}..."))
            started = time.perf_counter()
            result = self.model.transcribe(
                str(path),
                language=None if language == "auto" else language,
                word_timestamps=timestamps,
            )
            elapsed = time.perf_counter() - started

            text = result.text.strip() or "(no speech detected)"
            if timestamps and getattr(result, "words", None):
                lines = [f"{w.start:7.2f} - {w.end:7.2f}  {w.word}" for w in result.words]
                text += "\n\n--- Word timings ---\n" + "\n".join(lines)

            self.events.put(("done", (text, elapsed)))

        except Exception as exc:  # surface in the UI rather than dying silently
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()

                if kind == "status":
                    self._set_status(payload)

                elif kind == "done":
                    text, elapsed = payload
                    self.result_text = text
                    self.output.delete("1.0", "end")
                    self.output.insert("1.0", text)
                    self._set_status(f"Done in {elapsed:.1f}s")
                    self.save_btn.config(state="normal")
                    self.copy_btn.config(state="normal")
                    self._finish()

                elif kind == "error":
                    self._set_status("Failed")
                    self._finish()
                    messagebox.showerror("Transcription failed", payload)

        except queue.Empty:
            pass

        self.root.after(100, self._drain_events)

    def _finish(self):
        self.busy = False
        self.progress.stop()
        self.pick_btn.config(state="normal")
        if self.devices:
            self.rec_btn.config(state="normal")
            self.test_btn.config(state="normal")
        if self.audio_path:
            self.go_btn.config(state="normal")

    def _set_status(self, text):
        self.status.config(text=text)

    # ------------------------------------------------------------ outputs ----
    def save_text(self):
        if not self.result_text:
            return
        default = self.audio_path.with_suffix(".txt").name if self.audio_path else "transcript.txt"
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile=default,
            initialdir=desktop_dir(),
            filetypes=[("Text file", "*.txt")],
        )
        if path:
            Path(path).write_text(self.result_text, encoding="utf-8")
            self._set_status(f"Saved to {path}")

    def copy_text(self):
        if not self.result_text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.result_text)
        self._set_status("Copied to clipboard")

    def _on_close(self):
        self.recording = False
        self.testing = False
        self._close_stream()
        self.root.destroy()


if __name__ == "__main__":
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Flow.Transcribe")
    except Exception:
        pass
    root = tk.Tk()
    icon = Path(__file__).with_name("icon.ico")
    if icon.exists():
        ui.set_window_icon(root, icon)
    App(root)
    root.mainloop()
