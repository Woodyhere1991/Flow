"""Exercise recording decisions without opening devices or loading a model."""
import ast
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np


ROOT = Path(__file__).resolve().parent
if not (ROOT / "hotkey.py").exists():
    ROOT = ROOT.parent
tree = ast.parse((ROOT / "hotkey.py").read_text(encoding="utf-8"))
source_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Dictation")
methods = {"_toggle_voice_check", "_close_personalize", "_finish"}
namespace = dict(np=np, threading=threading, RATE=16000, IDLE="idle",
                 MIN_CLIP_SECONDS=0.25, SILENCE_PEAK=0.0002,
                 MIN_SPEECH_RMS=0.005, SPEECH_OVER_AMBIENT=1.8,
                 ui=SimpleNamespace(GOOD="green", WARN="amber", REC="red", TEXT="text"))
for method in source_class.body:
    if isinstance(method, ast.FunctionDef) and method.name in methods:
        exec(compile(ast.Module(body=[method], type_ignores=[]), "hotkey.py", "exec"), namespace)


class MicrophoneLifecycleTests(unittest.TestCase):
    def app(self, audio=None):
        app = SimpleNamespace(
            personalize_mark=None, model=object(), total=100, lock=threading.Lock(),
            mode="idle", busy=False, mark=0, ambient=0.012,
            loaded_engine="whisper", record_to_flow=True,
            personalize_window=Mock(), personalize_status=Mock(), voice_check_btn=Mock(),
            overlay=Mock(), talk_button=Mock(), text_mode=Mock(),
            show_overlay=Mock(), _ensure_microphone=Mock(return_value=True),
            _stop_stream=Mock(), _set_state=Mock(), _sound_stop=Mock(),
            _stop_conversation_watch=Mock(),
            _reset_main_recording=Mock(), _transcribe=Mock(), _transcribe_voice_check=Mock(),
            _grab=Mock(return_value=audio if audio is not None else np.ones(16000)*0.001),
        )
        return app

    def test_voice_check_replaces_starting_status(self):
        app = self.app()
        namespace["_toggle_voice_check"](app)
        self.assertEqual(app.personalize_mark, 100)
        app._set_state.assert_called_with("Listening - voice check", "red")
        app.overlay.show_listening.assert_called_once()

    def test_finished_voice_check_releases_mic_and_restores_ready(self):
        app = self.app()
        app.personalize_mark = 0
        with patch.object(threading, "Thread") as thread:
            namespace["_toggle_voice_check"](app)
            thread.return_value.start.assert_called_once()
        app._stop_stream.assert_called_once()
        app._set_state.assert_called_with("Ready to listen", "green")
        app.overlay.return_to_idle.assert_called_once()
        self.assertIsNone(app.personalize_mark)

    def test_short_voice_check_also_restores_ready(self):
        app = self.app(np.ones(100))
        app.personalize_mark = 0
        with patch.object(threading, "Thread") as thread:
            namespace["_toggle_voice_check"](app)
            thread.assert_not_called()
        app._set_state.assert_called_with("Ready to listen", "green")

    def test_closing_active_voice_check_releases_mic(self):
        app = self.app()
        app.personalize_mark = 0
        namespace["_close_personalize"](app)
        app._stop_stream.assert_called_once_with(clear_buffers=True)
        self.assertIsNone(app.personalize_mark)
        self.assertIsNone(app.personalize_window)
        app._set_state.assert_called_with("Ready to listen", "green")

    def test_closing_settings_does_not_interrupt_other_recording(self):
        app = self.app()
        app.mode = "ptt"
        namespace["_close_personalize"](app)
        app._stop_stream.assert_not_called()
        app._set_state.assert_not_called()

    def test_quiet_whisper_audio_reaches_speech_detector(self):
        app = self.app()
        with patch.object(threading, "Thread") as thread:
            namespace["_finish"](app)
            thread.return_value.start.assert_called_once()
        self.assertTrue(app.busy)

    def test_crisper_keeps_its_noise_gate(self):
        app = self.app()
        app.loaded_engine = "crisper"
        with patch.object(threading, "Thread") as thread:
            namespace["_finish"](app)
            thread.assert_not_called()
        self.assertFalse(app.busy)
        self.assertIn("too quiet", app._set_state.call_args.args[0])

    def test_silent_whisper_audio_is_rejected(self):
        app = self.app(np.zeros(16000))
        with patch.object(threading, "Thread") as thread:
            namespace["_finish"](app)
            thread.assert_not_called()
        app.overlay.show_done.assert_called_with("No sound", good=False)

    def test_whisper_transcription_enables_speech_detection(self):
        engine_tree = ast.parse((ROOT / "whisper_engine.py").read_text(encoding="utf-8"))
        method = next(n for n in engine_tree.body if isinstance(n, ast.FunctionDef) and n.name == "transcribe")
        scope = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "whisper_engine.py", "exec"), scope)
        model = Mock()
        model.transcribe.return_value = ([], None)
        self.assertEqual(scope["transcribe"](model, "silent.wav", None), "")
        self.assertTrue(model.transcribe.call_args.kwargs["vad_filter"])


if __name__ == "__main__":
    unittest.main()
