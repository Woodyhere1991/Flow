"""Deterministic one-turn (conversation_loop=False) tests for Flow.

No microphone, no listeners, no windows, no typing. Everything drives the
Dictation internals on a bare instance built with Dictation.__new__.
"""

import queue
import sys
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hotkey  # noqa: E402
from hotkey import Dictation, IDLE, TOGGLE, RATE  # noqa: E402


class FakeRoot:
    """Records after()/after_cancel() instead of running Tk."""

    def __init__(self):
        self.cancelled = []
        self.after_calls = []
        self._next = 0

    def after(self, ms, func):
        self._next += 1
        self.after_calls.append((self._next, ms, func))
        return self._next

    def after_cancel(self, job):
        self.cancelled.append(job)


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeVAD:
    """VAD stand-in: pops scripted outputs, else None."""

    def __init__(self, outputs=()):
        self.outputs = list(outputs)
        self.calls = 0

    def __call__(self, block):
        self.calls += 1
        return self.outputs.pop(0) if self.outputs else None


class FakeMouseData:
    def __init__(self, button):
        self.mouseData = button << 16


class FakeMouseListener:
    def __init__(self):
        self.suppressed = 0

    def suppress_event(self):
        self.suppressed += 1


def make_dictation(**overrides):
    d = Dictation.__new__(Dictation)
    d.root = FakeRoot()
    d.lock = threading.Lock()
    d.chunks = deque()
    d.total = 0
    d.dropped = 0
    d.mode = TOGGLE
    d.mark = None
    d.ambient = 0.0
    d.conversation_loop = FakeVar(False)
    d.events = queue.Queue()
    d._conv_silence_since = None
    d._conv_speech_seen = False
    d._conv_speech_level = 0.0
    d._conv_vad_iter = None
    d._conv_vad_pos = 0
    d._conv_vad_buf = np.zeros(0, dtype=np.float32)
    d._conv_watch_job = None
    d._mouse_x2_down = False
    d._set_state = mock.Mock()
    d._finish = mock.Mock()
    for key, value in overrides.items():
        setattr(d, key, value)
    return d


def feed(d, samples, loud=False):
    chunk = (np.full(samples, 0.5, dtype=np.float32) if loud
             else np.zeros(samples, dtype=np.float32))
    with d.lock:
        d.chunks.append(chunk)
        d.total += samples


class OneTurnGate(unittest.TestCase):
    """One-turn mode must ignore stale TTS gate state and never poll."""

    def test_stale_gate_fields_are_ignored_and_mark_preserved(self):
        d = make_dictation(_conv_gate_until=time.perf_counter() + 60.0,
                           _conv_last_piece_at=time.perf_counter(),
                           _conv_gated=True)
        feed(d, RATE // 2, loud=True)          # user starts speaking at once
        d.mark = 0                              # start-of-turn audio mark
        d._conv_vad_iter = FakeVAD([{"start": 1.0}])
        with mock.patch("urllib.request.urlopen") as urlopen:
            d._conv_watch_tick()
            urlopen.assert_not_called()
        self.assertEqual(d.mark, 0)             # speech NOT discarded
        self.assertTrue(d._conv_speech_seen)    # speech counted as the user's

    def test_no_urlopen_across_many_ticks(self):
        d = make_dictation()
        d._conv_vad_iter = FakeVAD()
        with mock.patch("urllib.request.urlopen") as urlopen:
            for _ in range(10):
                d._conv_watch_tick()
            urlopen.assert_not_called()


class VadEnd(unittest.TestCase):
    """A VAD end event finishes the turn exactly once."""

    def test_end_after_speech_finishes_once(self):
        d = make_dictation(_conv_speech_seen=True)
        feed(d, RATE // 2)
        d._conv_vad_iter = FakeVAD([{"end": 2.0}])
        d._conv_watch_tick()
        d._finish.assert_called_once()
        d._conv_vad_iter = FakeVAD()            # later ticks say nothing
        d._conv_watch_tick()
        d._finish.assert_called_once()          # still exactly once

    def test_end_without_prior_speech_does_not_finish(self):
        d = make_dictation(_conv_speech_seen=False)
        feed(d, RATE // 2)
        d._conv_vad_iter = FakeVAD([{"end": 2.0}])
        d._conv_watch_tick()
        d._finish.assert_not_called()


class RmsFallback(unittest.TestCase):
    """Loudness fallback runs only without VAD, and never before 3s."""

    def test_no_rms_fallback_while_vad_active(self):
        d = make_dictation()
        feed(d, RATE // 2, loud=True)
        d._conv_vad_iter = FakeVAD()            # VAD up, reports nothing
        d._conv_watch_tick()
        self.assertFalse(d._conv_speech_seen)   # loud audio did not count
        self.assertEqual(d._conv_speech_level, 0.0)
        self.assertIsNone(d._conv_silence_since)

    def test_rms_silence_not_before_3s(self):
        d = make_dictation(_conv_speech_seen=True, _conv_vad_iter=False)
        feed(d, RATE // 2)
        d._conv_silence_since = time.perf_counter() - 2.5
        d._conv_watch_tick()
        d._finish.assert_not_called()

    def test_rms_silence_finishes_at_3s(self):
        d = make_dictation(_conv_speech_seen=True, _conv_vad_iter=False)
        feed(d, RATE // 2)
        d._conv_silence_since = time.perf_counter() - 3.05
        d._conv_watch_tick()
        d._finish.assert_called_once()


class MouseFilter(unittest.TestCase):
    """The X2 win32 filter queues one toggle per press and eats only X2."""

    def setUp(self):
        self.d = make_dictation(mode=IDLE)
        self.d.mouse_listener = FakeMouseListener()

    def drained(self):
        out = []
        while True:
            try:
                out.append(self.d.events.get_nowait())
            except queue.Empty:
                return out

    def test_press_queues_once_release_never(self):
        self.assertTrue(self.d._mouse_event_filter(0x020B, FakeMouseData(2)))
        self.assertTrue(self.d._mouse_event_filter(0x020C, FakeMouseData(2)))
        self.assertEqual(self.drained(), [("mouse_toggle", None)])
        self.assertEqual(self.d.mouse_listener.suppressed, 2)

    def test_auto_repeat_press_does_not_queue_again(self):
        self.d._mouse_event_filter(0x020B, FakeMouseData(2))
        self.d._mouse_event_filter(0x020B, FakeMouseData(2))  # OS repeat
        self.assertEqual(self.drained(), [("mouse_toggle", None)])

    def test_second_press_after_release_queues_again(self):
        self.d._mouse_event_filter(0x020B, FakeMouseData(2))
        self.d._mouse_event_filter(0x020C, FakeMouseData(2))
        self.d._mouse_event_filter(0x020B, FakeMouseData(2))
        self.assertEqual(
            self.drained(), [("mouse_toggle", None), ("mouse_toggle", None)])

    def test_other_buttons_pass_through_untouched(self):
        suppressed_before = self.d.mouse_listener.suppressed
        for msg in (0x020B, 0x020C):
            self.assertTrue(self.d._mouse_event_filter(msg, FakeMouseData(1)))
        self.assertTrue(self.d._mouse_event_filter(0x0201, FakeMouseData(0)))
        self.assertEqual(self.drained(), [])
        self.assertEqual(self.d.mouse_listener.suppressed, suppressed_before)


class WatcherScheduling(unittest.TestCase):
    """One chain at a time; it stops after the turn finishes."""

    def test_rescheduling_cancels_previous_chain(self):
        d = make_dictation()
        d._schedule_conversation_watch()
        first = d._conv_watch_job
        self.assertIsNotNone(first)
        d._schedule_conversation_watch()
        self.assertEqual(d.root.cancelled, [first])
        self.assertEqual(d._conv_watch_job, first + 1)

    def test_watcher_ticks_then_reschedules_while_toggle(self):
        d = make_dictation()
        d._conv_watch_tick = mock.Mock()
        d._watch_conversation_silence()
        d._conv_watch_tick.assert_called_once()
        self.assertIsNotNone(d._conv_watch_job)
        self.assertEqual(len(d.root.after_calls), 1)
        self.assertEqual(d.root.after_calls[0][1], 200)

    def test_watcher_stops_after_finish(self):
        d = make_dictation(mode=TOGGLE)
        d._conv_watch_job = 99
        d.mode = IDLE                            # what _finish leaves behind
        d._watch_conversation_silence()
        self.assertEqual(d.root.after_calls, [])  # no reschedule
        self.assertIsNone(d._conv_watch_job)

    def test_finish_cancels_the_chain(self):
        d = make_dictation(_stop_conversation_watch=mock.Mock(),
                           _stop_stream=mock.Mock(),
                           _reset_main_recording=mock.Mock())
        d._finish = Dictation._finish.__get__(d)  # run the real method
        d._finish()                              # mark None: early-out path
        d._stop_conversation_watch.assert_called_once()
        self.assertEqual(d.mode, IDLE)


class TurnStart(unittest.TestCase):
    """A press starts the turn with the mark at the first sample."""

    def test_mouse_toggle_start_sets_mark_and_single_chain(self):
        d = make_dictation(mode=IDLE, mark=None, model=object(),
                           busy=False, _busy=False,
                           show_overlay=FakeVar(False),
                           _sound_start=mock.Mock(),
                           _ensure_microphone=mock.Mock(return_value=True),
                           _capture_target=mock.Mock(),
                           overlay=mock.Mock())
        feed(d, RATE // 4)                       # mic warm-up audio exists
        start = d.total
        d._on_mouse_toggle()
        self.assertEqual(d.mode, TOGGLE)
        self.assertEqual(d.mark, start)
        self.assertFalse(d._conv_speech_seen)
        self.assertEqual(len(d.root.after_calls), 1)
        # Speech in the first moments must not move the mark.
        feed(d, RATE // 2, loud=True)
        d._conv_vad_iter = FakeVAD([{"start": 1.0}])
        d._conv_watch_tick()
        self.assertEqual(d.mark, start)


if __name__ == "__main__":
    unittest.main()
