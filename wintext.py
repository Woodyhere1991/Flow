"""
Windows helpers for putting transcribed text where the user is typing.

Kept separate from the hotkey logic so it can be tested on its own:
    python wintext.py
"""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ctypes defaults every restype to C int (32-bit). On 64-bit Windows that
# silently truncates returned HANDLEs and pointers, which crashes the process
# rather than raising, so every handle-returning call must be declared.
LPVOID = ctypes.c_void_p
HANDLE = wintypes.HANDLE

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, HANDLE]
user32.SetClipboardData.restype = HANDLE
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = HANDLE
kernel32.GlobalLock.argtypes = [HANDLE]
kernel32.GlobalLock.restype = LPVOID
kernel32.GlobalUnlock.argtypes = [HANDLE]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [HANDLE]
kernel32.GlobalFree.restype = HANDLE

SW_RESTORE = 9

user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetActiveWindow.argtypes = [wintypes.HWND]
user32.SetActiveWindow.restype = wintypes.HWND
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

VK_CONTROL = 0x11
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt
VK_V = 0x56
VK_Z = 0x5A

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1


# --------------------------------------------------------------- structs ----
class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    # MOUSEINPUT is the largest member. It must be present even though we only
    # ever send keyboard events: SendInput validates cbSize against the full
    # 40-byte INPUT, and a union sized only for KEYBDINPUT gives 32 - the call
    # then fails outright and sends nothing.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


assert ctypes.sizeof(INPUT) == 40, f"INPUT must be 40 bytes on x64, got {ctypes.sizeof(INPUT)}"


user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


# ------------------------------------------------------------- clipboard ----
def get_clipboard_text():
    """Current clipboard text, or None. Never raises."""
    try:
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.c_wchar_p(ptr).value
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def set_clipboard_text(text):
    """Put text on the clipboard. True on success."""
    buf = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buf)

    for _ in range(5):  # another app may hold the clipboard briefly
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False

    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, buf, size)
        kernel32.GlobalUnlock(handle)
        # After SetClipboardData succeeds the system owns the memory.
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


# ------------------------------------------------------------ focus info ----
def _gui_info():
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    fg = user32.GetForegroundWindow()
    if not fg:
        return None
    tid = user32.GetWindowThreadProcessId(fg, None)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return None
    return info


def get_foreground_window():
    """HWND of whatever window is active right now (0 if none)."""
    return user32.GetForegroundWindow()


def window_title(hwnd):
    if not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def force_foreground(hwnd):
    """Make hwnd the foreground window, working around the foreground lock.

    Windows refuses SetForegroundWindow from a process that does not own the
    current foreground. Attaching our input queue to the foreground thread
    lifts that restriction for the duration of the call, which is what every
    dictation/launcher tool has to do to restore the user's original window.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    ours = kernel32.GetCurrentThreadId()
    target = user32.GetWindowThreadProcessId(hwnd, None)
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0

    attached = []
    for tid in {target, fg_thread} - {0, ours}:
        if user32.AttachThreadInput(ours, tid, True):
            attached.append(tid)
    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        for tid in attached:
            user32.AttachThreadInput(ours, tid, False)

    return user32.GetForegroundWindow() == hwnd


def focused_window_title():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def has_text_cursor():
    """True when the focused window looks like it has an editable text caret.

    Uses GetGUIThreadInfo's caret handle. This is a heuristic: it is reliable
    for classic Win32 edit controls and most editors/terminals, but some
    Electron and UWP apps draw their own caret and report nothing, so a False
    here does not strictly prove there is nowhere to type.
    """
    info = _gui_info()
    if info is None:
        return False
    if info.hwndCaret:
        return True
    # Some apps report the caret rect without a caret window handle.
    rc = info.rcCaret
    return bool(info.hwndFocus) and (rc.bottom - rc.top) > 0


# ----------------------------------------------------------- key sending ----
def _send(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    return sent == n


def _key(vk, up=False):
    return INPUT(type=INPUT_KEYBOARD,
                 ki=KEYBDINPUT(wVk=vk, wScan=0,
                               dwFlags=KEYEVENTF_KEYUP if up else 0,
                               time=0, dwExtraInfo=None))


def release_modifiers():
    """Force-release modifiers we might still be holding.

    Critical before sending Ctrl+V: if Win is still physically down, the V
    lands as Win+V and opens clipboard history instead of pasting.
    """
    ups = [_key(vk, up=True) for vk in (VK_LWIN, VK_RWIN, VK_CONTROL, VK_SHIFT, VK_MENU)]
    _send(*ups)


def send_paste():
    """Send Ctrl+V to the focused window."""
    return _send(_key(VK_CONTROL), _key(VK_V),
                 _key(VK_V, up=True), _key(VK_CONTROL, up=True))


def undo_in_window(target_hwnd):
    """Send one Ctrl+Z to a specific window."""
    if not target_hwnd or not force_foreground(target_hwnd):
        return False
    release_modifiers()
    time.sleep(0.06)
    return _send(_key(VK_CONTROL), _key(VK_Z),
                 _key(VK_Z, up=True), _key(VK_CONTROL, up=True))


def type_unicode(text):
    """Type text character by character - no clipboard involved.

    Slower than pasting and some apps drop fast synthetic input, so this is
    the fallback rather than the default.
    """
    inputs = []
    for ch in text:
        for up in (False, True):
            flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
            inputs.append(INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=flags,
                              time=0, dwExtraInfo=None),
            ))
    # Send in chunks; very long single SendInput calls can be dropped.
    for i in range(0, len(inputs), 200):
        chunk = inputs[i:i + 200]
        if not _send(*chunk):
            return False
        time.sleep(0.002)
    return True


def insert_text(text, restore_clipboard=False, target_hwnd=None):
    """Paste text into target_hwnd (or whatever has focus if not given).

    target_hwnd matters: by the time a transcript is ready the user may have
    clicked our own window, and pasting into "whatever is focused now" would
    drop the text there instead of where they were typing. The caller captures
    the window at the moment recording started and passes it here.

    restore_clipboard defaults to False, deliberately. Ctrl+V is delivered
    asynchronously - the target app reads the clipboard whenever it gets round
    to processing the keystroke. Putting the old contents back after a fixed
    delay is a race, and losing it means the app pastes the WRONG text (this
    was observed: the previous clipboard entry got pasted instead of the new
    transcript). Leaving the transcript on the clipboard also doubles as the
    "copy" fallback.

    Returns (ok, method). Falls back to synthetic typing if the paste does not
    take, and leaves the text on the clipboard either way so nothing is lost.
    """
    previous = get_clipboard_text() if restore_clipboard else None

    if not set_clipboard_text(text):
        return False, "clipboard-failed"

    if target_hwnd and not force_foreground(target_hwnd):
        # Could not get back to the user's window - do not paste blindly into
        # whatever is in front, the text is on the clipboard for them instead.
        return False, "lost-focus"

    release_modifiers()
    time.sleep(0.06)  # let the target app see the modifiers go up

    ok = send_paste()
    method = "paste"

    if not ok:
        ok = type_unicode(text)
        method = "typed"

    if previous is not None and previous != text:
        # Give the target time to actually read the clipboard before restoring.
        time.sleep(0.35)
        set_clipboard_text(previous)

    return ok, method


if __name__ == "__main__":
    print("focused window :", focused_window_title())
    print("has text caret :", has_text_cursor())
    original = get_clipboard_text()
    print("clipboard now  :", repr(original)[:80])
    set_clipboard_text("crisperwhisper clipboard test")
    print("after set      :", repr(get_clipboard_text())[:80])
    if original is not None:
        set_clipboard_text(original)
        print("restored       :", repr(get_clipboard_text())[:80])
