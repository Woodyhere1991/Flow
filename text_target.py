"""Capture an editable field, not just its window; verify text before Enter.

UI Automation is Windows' accessibility API. Browser fields have no HWND
of their own, so restoring the browser window alone does not focus the chat.
Imports are lazy: a missing accessibility provider must leave a clipboard
fallback, never make Flow fail to start.
"""

import logging
import time
from dataclasses import dataclass

import wintext

log = logging.getLogger("flow")
CHAT_INPUT_NAME = "Message or run a task, / commands, @ files or sessions"


@dataclass
class TextTarget:
    hwnd: int
    automation: object
    element: object
    value_pattern: object
    is_chat: bool = False
    name: str = ""
    last_value: str | None = None
    title: str | None = None

    def _same_window(self):
        return (wintext.get_foreground_window() == self.hwnd
                and (not self.is_chat or self.title is None
                     or wintext.window_title(self.hwnd) == self.title))

    def value(self):
        return self.value_pattern.CurrentValue

    def _has_focus(self):
        return self._same_window() and bool(self.automation.CompareElements(
            self.element, self.automation.GetFocusedElement()))

    def _focus(self):
        if (not self.element.CurrentIsEnabled
                or self.element.CurrentIsOffscreen
                or self.value_pattern.CurrentIsReadOnly):
            return False
        if (self.is_chat and self.title is not None
                and wintext.window_title(self.hwnd) != self.title):
            return False  # User changed tabs/sessions during this recording.
        if not wintext.force_foreground(self.hwnd):
            return False
        self.element.SetFocus()
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if self._same_window() and self._has_focus():
                return True
            time.sleep(0.025)
        return False

    def insert(self, text, timeout=1.5):
        """Return success only after the captured field contains new text.

        Never resend a paste just because the app is slow. That could duplicate
        the transcript. On any failure it remains on the clipboard.
        """
        self.last_value = None
        if not wintext.set_clipboard_text(text):
            return False, "clipboard-failed"
        try:
            if not self._focus():
                return False, "field-not-focused"
            before = self.value()
            wintext.release_modifiers()
            time.sleep(0.06)
            if not self._has_focus():
                return False, "focus-changed"
            if not wintext.send_paste():
                return False, "input-rejected"
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not self._has_focus():
                    return False, "focus-changed"
                after = self.value()
                if after != before and text in after:
                    self.last_value = after
                    return True, "verified-paste"
                time.sleep(0.025)
            return False, "paste-not-observed"
        except Exception:
            log.warning("Captured text field is unavailable", exc_info=True)
            return False, "field-unavailable"

    def submit(self, timeout=2.0):
        """Submit a verified DSH draft, then observe the input clearing.

        Clearing confirms the browser handled Enter, not that a remote model
        finished the message. Never send Enter to an unknown app or a draft
        changed by the user while Flow was delivering.
        """
        if not self.is_chat or self.last_value is None:
            return False, "not-a-verified-chat-draft"
        try:
            if (not self._same_window() or not self._has_focus()
                    or self.value() != self.last_value):
                return False, "draft-or-focus-changed"
            if not wintext.send_enter():
                return False, "enter-rejected"
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not self.value().strip():
                    # Chromium reports an empty contenteditable as '\n'.
                    return True, "chat-input-cleared"
                time.sleep(0.025)
            return False, "draft-not-submitted"
        except Exception:
            log.warning("Could not verify chat submission", exc_info=True)
            return False, "submission-unverified"


def _capture_once(hwnd):
    """Remember the chat composer or the currently focused editable field.

    For DSH, locate its composer even when a message or the page background
    has focus. Do not substitute the address bar or session search box.
    The captured element is kept for this turn only; navigation invalidates it.
    """
    if not hwnd:
        return None
    try:
        import comtypes.client
        api = comtypes.client.GetModule("UIAutomationCore.dll")
        automation = comtypes.client.CreateObject(
            api.CUIAutomation, interface=api.IUIAutomation)
        root = automation.ElementFromHandle(hwnd)
        is_chat = "DeepSeek Harness" in wintext.window_title(hwnd)
        if is_chat:
            condition = automation.CreateAndCondition(
                automation.CreatePropertyCondition(
                    api.UIA_ControlTypePropertyId, api.UIA_EditControlTypeId),
                automation.CreatePropertyCondition(
                    api.UIA_NamePropertyId, CHAT_INPUT_NAME))
            fields = root.FindAll(api.TreeScope_Descendants, condition)
            visible = [fields.GetElement(i) for i in range(fields.Length)
                       if not fields.GetElement(i).CurrentIsOffscreen]
            if len(visible) != 1:
                log.warning("Expected one visible DSH message box; found %d",
                            len(visible))
                return None
            element = visible[0]
            # Chromium can expose a field's name before it exposes its value
            # pattern. Focus the composer, then ask for the focused provider.
            element.SetFocus()
            element = automation.GetFocusedElement()
            if element.CurrentName != CHAT_INPUT_NAME:
                return None
        else:
            element = automation.GetFocusedElement()
            if not element or not element.CurrentIsKeyboardFocusable:
                return None
            # Do not bind a control from another top-level window.
            ancestor = element
            while ancestor and not automation.CompareElements(ancestor, root):
                ancestor = automation.ControlViewWalker.GetParentElement(ancestor)
            if not ancestor:
                return None
        pattern = element.GetCurrentPattern(api.UIA_ValuePatternId).QueryInterface(
            api.IUIAutomationValuePattern)
        if pattern.CurrentIsReadOnly or not element.CurrentIsEnabled:
            return None
        return TextTarget(hwnd, automation, element, pattern,
                          is_chat=is_chat, name=element.CurrentName,
                          title=wintext.window_title(hwnd))
    except Exception:
        log.debug("Text field provider not ready", exc_info=True)
        return None


def capture(hwnd):
    # A streamed page update can replace the accessibility provider just as
    # the user presses the button. Retry capture, never retry pasted text.
    for _ in range(4):
        target = _capture_once(hwnd)
        if target is not None:
            return target
        time.sleep(0.075)
    log.warning("No verifiable text field found for hwnd=%s", hwnd)
    return None
