# Flow — local dictation

Hold **Ctrl + Win**, talk, let go, and it types what you said into whatever app
you're using. Everything runs on your own PC — no account, no subscription, no
internet, and your voice never leaves the machine.

Built on CrisperWhisper, a variant of OpenAI's Whisper that can transcribe
either **verbatim** (keeping every "um", stutter and false start) or
**intended** (what you meant to say, tidied up).

## Install on another PC

**You need:** Windows 10 or 11 and an internet connection while setup runs.
The installer gets Python, Flow's AI components, and the default speech model.
After setup finishes, normal dictation works offline.

### Installer temporarily unavailable

The first public installer was not digitally signed, so Windows showed
**Unknown publisher**. It has been withdrawn rather than asking people to
bypass a security warning. A normal one-click installer will return after it
has a verified digital signature.

Setup checks each computer before large downloads begin:

| Computer | Automatic setup |
|---|---|
| Supported NVIDIA graphics | CUDA acceleration + Turbo model |
| No supported NVIDIA graphics | CPU engine + smaller Small model |
| Low-memory or low-core CPU | Small model + a clear **may not be useful** warning |

The installer asks before continuing with a CPU-only setup. Flow also shows the
hardware result in the app. It never silently chooses the slow CPU engine when
an NVIDIA card was detected but could not be enabled.

For now, experienced users can inspect the public source and use the ZIP version:

```bash
git clone <this-repo-url>
```

Open the folder and **double-click `Install Flow.bat`**. It creates an isolated
environment, installs everything (about 3 GB of downloads), generates the icon
and puts a **Flow** shortcut on the Desktop. It takes 5–15 minutes depending on
your connection.

The speech model recommended for that computer downloads during setup, not on
first launch. Choosing a different model later may require internet once.

**Windows only.** Typing into other apps uses Win32 APIs (`SendInput`,
clipboard, foreground-window handling) that have no macOS or Linux equivalent
here.

## How to use Flow

Double-click **Flow** on the Desktop. The main screen explains everything.

The easiest way:

1. Click **Start talking**.
2. Speak naturally.
3. Click **Stop and write**. Your words appear in Flow and are copied for you.

To speak directly into an email, document, or other app:

1. Click where you want the words to appear.
2. Hold the **Ctrl** and **Windows** keys while you speak.
3. Let go when you are finished. Flow types the words there.

For hands-free listening, quickly tap **Ctrl + Windows** twice. Flow keeps
listening until you press **Ctrl + Windows** once more.

If Windows cannot find a microphone, Flow clearly says **No microphone
connected** when you try to listen. Connect a microphone and try again.
If you connect a headset while Flow is already open, it notices automatically
and changes to **Microphone connected - ready to listen**.

Flow normally follows the microphone selected in Windows. If Windows chooses
the wrong one, open **Settings** and choose a microphone from the simple list.
Flow remembers its name rather than Windows' temporary device number and falls
back to the Windows default if that microphone disappears. If a microphone is
connected but the signal is too quiet, Flow says so instead of guessing words.

Click **Personalize Flow**, then **Fix latest dictation** after Flow gets a word
wrong. Correct it once and save it. Flow automatically remembers a simple
spelling change for next time, so you do not need to fill in both manual boxes.
The manual boxes are still available for special names, email addresses, and
phrases. Click **Undo typing** within 30 seconds to remove the most recent
dictation.

Personal rules stay in `%LOCALAPPDATA%\Flow\settings.json`, outside OneDrive
and outside the project folder. They are not uploaded to GitHub. The text is
always copied too, so nothing is lost if Flow cannot type into another app.

### Writing style: Clean vs Word for word

Both are native model capabilities, not text post-processing:

| Style | Same sentence, dictated |
|---|---|
| **Clean** (default) | "Can you please make it so there's something like Whisperflow has..." |
| **Word for word** | "Can you please [UM] make it so there's a something like WhisperFlow has..." |

**Word for word** keeps every filler, stutter, false start, and marks `[breath]`,
`[laugh]` and similar. **Clean** gives you what you meant to say, with
punctuation tidied.

### Speed

Measured on an NVIDIA RTX 4060 with weights already cached:

| Model | Startup | Per phrase |
|---|---|---|
| **Turbo** (default) | 8s | 1.1s |
| Small | 6s | 1.2s |
| Large | 17s | 3.8s |

Turbo is recommended automatically for supported NVIDIA computers. Small is
recommended for CPU-only computers because it is much less demanding. Even
Small can be slow on an older CPU, so setup warns before downloading it.

Switch on **Start with Windows** and the model loads at login, so it is always
warm by the time you need it.

### Privacy

The mic is held **open the whole time Dictate is running**. That's deliberate:
a mic takes ~0.65s to wake up, so opening it on keypress would swallow your
first word. Audio stays in memory as a rolling 2-minute window, is never
written to disk except for the temporary clip being transcribed, and never
leaves the PC. The temporary file is deleted immediately after transcription.
Closing the window releases the mic.

### Two things it handles for you

- **Pre-roll.** It keeps 0.35s of audio from *before* you pressed the keys, so
  starting to talk a fraction early doesn't clip your first word.
- **Noise markers.** CrisperWhisper transcribes verbatim, so an empty room
  produces `[breath]` or `[lipsmack]`. Those are filtered out — a result made
  only of them types nothing at all, rather than pasting junk into your
  document. Newlines are also stripped, since pasting one into a terminal
  would run the line as a command.

## The app (easiest)

Double-click **Transcribe** on the Desktop, or `Transcribe.bat` in this folder.

- **Start recording** — talk into the mic, hit stop, and it transcribes.
- **Choose audio file** — transcribe a file instead.
- **Save as .txt** / **Copy** — get the text out.

The first transcription of each session takes longer while the model loads
into memory. Every one after that is faster.

## Microphone setup

Bluetooth headsets run in one of two modes, and only one of them has a mic:

| Mode | Sound quality | Mic |
|---|---|---|
| A2DP / Stereo | High | No |
| Hands-Free (HFP) | Noticeably worse | Yes |

To switch, open **Settings > System > Sound > Input**, choose the headset's
*Hands-Free* entry, then select **Refresh** in Flow. Audio playback will sound
worse while it is in this mode; that is a Bluetooth limitation, not a Flow
problem.

Any cheap USB microphone or webcam would sidestep the whole issue and sound
better, if you plan to do this often.

### If it doesn't hear you

Click **Test mic** and watch the meter while you talk. It shows a live level in
dB — green is good, amber is quiet but usable, red means no signal.

Two things were fixed after the first attempt at this, both worth knowing:

- **The mic takes ~0.65s to wake up.** Opening an input stream isn't instant
  (WASAPI measured 0.64–2.0s depending on backend). The app now waits for the
  first real audio frame before it says "Recording", and throws the warm-up
  away — otherwise your first words vanish.
- **Don't boost quiet audio.** An earlier version normalised the level, which
  seemed sensible for a quiet Bluetooth mic. It backfired: Whisper already
  normalises internally and transcribes quiet audio just as accurately, so the
  only effect was amplifying room hiss until the model hallucinated speech out
  of it ("What's the weather in New Year's Eve?" from an empty room). Measured,
  then removed.

Backends aren't equal, either. Measured over two runs each, capturing 2s:

| Backend | Warm-up | Captured | Signal |
|---|---|---|---|
| **WASAPI** (default) | 0.65s | 1.7–1.8s | strongest |
| WDM-KS | 0.66s | 1.4–1.5s | inconsistent |
| MME | 0.66–1.6s | 0.9–1.1s | very weak |
| DirectSound | 0.79–2.0s | 0.6s | very weak |

The app picks WASAPI automatically. Only change the Mic dropdown if that one
misbehaves.

## Command line

Basic transcription:

```bash
venv\Scripts\python.exe transcribe.py your-audio.wav
```

With per-word start/end times:

```bash
venv\Scripts\python.exe transcribe.py your-audio.wav --timestamps
```

Faster, slightly less accurate (options: `large`, `medium`, `small`, `turbo`):

```bash
venv\Scripts\python.exe transcribe.py your-audio.wav --model turbo
```

Another language (any Whisper language code):

```bash
venv\Scripts\python.exe transcribe.py audio.mp3 --language de
```

## Verified working

Tested 2026-08-02 on this machine — RTX 4060, transcribed a 10s clip in 3.4s
with correct text and sensible word timings.

## What's installed

| Thing | Where | Size |
|---|---|---|
| Python 3.12.10 | `%LOCALAPPDATA%\Programs\Python\Python312` | — |
| Virtual environment | `venv\` | ~4.7 GB |
| Model weights | `%USERPROFILE%\.cache\huggingface` | ~2.9 GB |
| ffmpeg | via winget (`Gyan.FFmpeg`) | — |
| sounddevice | in `venv` (mic capture) | — |

The `venv` folder keeps these packages isolated, so they can't break anything
else on the system. Deleting `venv\` and the huggingface cache undoes the whole
install.

## Two Windows-specific gotchas

Both are already handled in `transcribe.py`, but worth knowing if you rebuild
this from scratch:

1. **`backend="transformers"` is required.** CrisperWhisper's faster CT2 backend
   needs `ctranslate2-crisperwhisper`, a custom fork that only ships Linux
   wheels. On Windows we use the PyTorch backend — still GPU-accelerated, just
   without speculative decoding (~1.3–1.4x slower than the Linux path).

2. **Stock `ctranslate2` must stay installed.** `crisperwhisper/hallucination.py`
   imports it unconditionally at module level, even on the PyTorch path, so
   transcription crashes without it. It's only used for its type annotations
   here — the repair helpers themselves are pure Python/numpy. But because the
   library's `backend="auto"` picks CT2 whenever `ctranslate2` is importable,
   the backend must be pinned explicitly, or it selects CT2 and fails on the
   missing fork APIs.

## Rebuilding from scratch

```bash
python -m venv venv
venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
venv\Scripts\python.exe -m pip install "crisperwhisper[transformers]" ctranslate2
```
