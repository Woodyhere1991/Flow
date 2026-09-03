r"""
Tiny earcons for dictation: a blip when recording starts, another when it
stops.

Synthesised at runtime with numpy - there are no audio files to ship or
lose. Both sounds are deliberately very short and quiet: if a speaker blip
ever bleeds into an open microphone, the engines' silence and noise
handling drops it instead of transcribing it. Playback is non-blocking
(sounddevice runs it on its own stream), so calling these from the UI
thread never stalls dictation.
"""

import logging

import numpy as np
import sounddevice as sd

log = logging.getLogger("flow")

RATE = 44100
VOLUME = 0.2


def _tone(freq, ms):
    seconds = ms / 1000
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    # 5ms fades on both ends so the tone does not click.
    fade = np.minimum(t, seconds - t) / 0.005
    tone = np.sin(2 * np.pi * freq * t) * np.clip(fade, 0.0, 1.0)
    return (tone * VOLUME).astype("float32")


def play_start():
    """Two quick rising tones: 'go ahead'."""
    try:
        sd.play(np.concatenate([_tone(660, 45), _tone(990, 55)]), RATE)
    except Exception:
        log.warning("start sound failed", exc_info=True)


def play_stop():
    """One soft falling tone: 'got it'."""
    try:
        sd.play(np.concatenate([_tone(880, 35), _tone(587, 60)]), RATE)
    except Exception:
        log.warning("stop sound failed", exc_info=True)
