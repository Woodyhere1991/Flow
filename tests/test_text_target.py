"""No real keyboard, clipboard, browser, microphone, or network operations."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import text_target
import hotkey


class VerifiedFieldTests(unittest.TestCase):
    def setUp(self):
        self.pattern = SimpleNamespace(CurrentValue="", CurrentIsReadOnly=False)
        self.element = SimpleNamespace(CurrentIsEnabled=True, CurrentIsOffscreen=False,
                                       SetFocus=Mock())
        self.automation = Mock()
        self.automation.CompareElements.return_value = True
        self.target = text_target.TextTarget(
            10, self.automation, self.element, self.pattern,
            is_chat=True, name="chat input", title="A - DeepSeek Harness")
        self.patches = [
            patch.object(text_target.wintext, "set_clipboard_text", return_value=True),
            patch.object(text_target.wintext, "force_foreground", return_value=True),
            patch.object(text_target.wintext, "get_foreground_window", return_value=10),
            patch.object(text_target.wintext, "window_title", return_value=self.target.title),
            patch.object(text_target.wintext, "release_modifiers"),
            patch.object(text_target.wintext, "send_paste", return_value=True),
            patch.object(text_target.wintext, "send_enter", return_value=True),
            patch.object(text_target.time, "sleep"),
        ]
        self.mocks = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def paste(self, text="hello"):
        def received():
            self.pattern.CurrentValue = text
            return True
        text_target.wintext.send_paste.side_effect = received
        return self.target.insert(text, timeout=0.03)

    def test_os_accepting_paste_is_not_delivery(self):
        ok, reason = self.target.insert("hello", timeout=0.01)
        self.assertFalse(ok)
        self.assertEqual(reason, "paste-not-observed")
        self.assertIsNone(self.target.last_value)
        text_target.wintext.send_enter.assert_not_called()
        text_target.wintext.send_paste.assert_called_once()

    def test_paste_is_verified_by_visible_text(self):
        self.assertEqual(self.paste(), (True, "verified-paste"))
        self.assertEqual(self.target.last_value, "hello")
        text_target.wintext.send_enter.assert_not_called()

    def test_changed_session_never_receives_paste(self):
        text_target.wintext.window_title.return_value = "Other - DeepSeek Harness"
        self.assertEqual(self.target.insert("hello"), (False, "field-not-focused"))
        text_target.wintext.send_paste.assert_not_called()

    def test_hidden_field_never_receives_paste(self):
        self.element.CurrentIsOffscreen = True
        self.assertFalse(self.target.insert("hello")[0])
        text_target.wintext.send_paste.assert_not_called()

    def test_clipboard_error_does_not_type(self):
        text_target.wintext.set_clipboard_text.return_value = False
        self.assertEqual(self.target.insert("hello"), (False, "clipboard-failed"))
        text_target.wintext.send_paste.assert_not_called()

    def test_input_rejection_is_not_retried(self):
        text_target.wintext.send_paste.return_value = False
        self.assertEqual(self.target.insert("hello"), (False, "input-rejected"))
        text_target.wintext.send_paste.assert_called_once()

    def test_cannot_submit_unverified_draft(self):
        self.assertFalse(self.target.submit()[0])
        text_target.wintext.send_enter.assert_not_called()

    def test_cannot_submit_changed_draft(self):
        self.paste()
        self.pattern.CurrentValue = "something the user typed"
        self.assertFalse(self.target.submit()[0])
        text_target.wintext.send_enter.assert_not_called()

    def test_cannot_send_enter_to_other_app(self):
        self.paste()
        self.target.is_chat = False
        self.assertFalse(self.target.submit()[0])
        text_target.wintext.send_enter.assert_not_called()

    def test_enter_success_is_not_a_submission_without_clear(self):
        self.paste()
        self.assertEqual(self.target.submit(timeout=0.01),
                         (False, "draft-not-submitted"))
        text_target.wintext.send_enter.assert_called_once()

    def test_submission_detects_browser_empty_newline(self):
        self.paste()
        def accepted():
            self.pattern.CurrentValue = "\n"
            return True
        text_target.wintext.send_enter.side_effect = accepted
        self.assertEqual(self.target.submit(timeout=0.03),
                         (True, "chat-input-cleared"))


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.d = hotkey.Dictation.__new__(hotkey.Dictation)
        self.d.record_to_flow = False
        self.d._reset_main_recording = Mock()
        self.d._show_transcript = Mock()
        self.d._set_state = Mock()
        self.d.spoken_replacements = {}
        self.d.personal_names = set()
        self.d.auto_paste = Mock(get=lambda: True)
        self.d.conversation_submit = Mock(get=lambda: True)
        self.d.conversation_loop = Mock(get=lambda: False)
        self.d.target_hwnd = 10
        self.d.root = Mock()
        self.d.overlay = Mock()
        self.d.text_target = Mock(name="field")
        self.d.text_target.name = "chat input"
        self.d.text_target.insert.return_value = (True, "verified-paste")
        self.d.text_target.submit.return_value = (True, "chat-input-cleared")

    @patch.object(hotkey.wintext, "set_clipboard_text", return_value=True)
    def test_missing_field_copies_and_does_not_claim_sent(self, clipboard):
        self.d.text_target = None
        self.d._deliver("hello")
        clipboard.assert_called_once_with("hello")
        self.d.overlay.show_done.assert_called_once_with(
            "Copied - click the message box", good=False)
        self.d.root.after.assert_not_called()

    @patch.object(hotkey.wintext, "send_enter")
    @patch.object(hotkey.wintext, "insert_text", return_value=(True, "paste"))
    def test_plain_dictation_keeps_non_accessible_editors(self, insert, enter):
        self.d.text_target = None
        self.d.conversation_submit.get = lambda: False
        self.d._deliver("hello")
        insert.assert_called_once_with("hello", target_hwnd=10)
        enter.assert_not_called()
        self.d.overlay.show_done.assert_called_once_with("Paste requested", good=True)

    def test_failed_paste_does_not_submit(self):
        self.d.text_target.insert.return_value = (False, "paste-not-observed")
        self.d._deliver("hello")
        self.d.text_target.submit.assert_not_called()
        self.d.root.after.assert_not_called()

    def test_verified_one_turn_does_not_restart_listening(self):
        self.d._deliver("hello")
        self.d.text_target.submit.assert_called_once()
        self.d.overlay.show_done.assert_called_once_with("Sent 1 words")
        self.d.root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
