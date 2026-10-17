"""
pcsx2_controller.py — Send PS2 controller inputs to PCSX2 via Win32 SendInput.

PCSX2.ini [Pad1] keyboard bindings (keyboard-only, no SDL):
  Up       = Keyboard/Up
  Down     = Keyboard/Down
  Left     = Keyboard/Left
  Right    = Keyboard/Right
  Cross    = Keyboard/Z      (confirm / select)
  Circle   = Keyboard/X      (back / cancel)
  Triangle = Keyboard/C
  Square   = Keyboard/V
  Start    = Keyboard/Return
  Select   = Keyboard/Back   (Backspace)
  L1       = Keyboard/Q
  L2       = Keyboard/W
  R1       = Keyboard/E
  R2       = Keyboard/R

Uses SendInput (not PostMessage) — requires PCSX2 to be the foreground window,
which we enforce with SetForegroundWindow before each send.
"""

import ctypes
import ctypes.wintypes as W
import time

user32  = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

INPUT_KEYBOARD    = 1
KEYEVENTF_KEYUP      = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001  # required for arrow keys, Insert, Delete, etc.

# Keys that need the extended flag
EXTENDED_KEYS = {0x25, 0x26, 0x27, 0x28,  # Left, Up, Right, Down arrows
                 0x21, 0x22, 0x23, 0x24,  # PageUp, PageDown, End, Home
                 0x2D, 0x2E,               # Insert, Delete
                 0x11, 0x12}              # Ctrl, Alt (right-side)

# Virtual key codes matching the Keyboard/X bindings in PCSX2.ini
VK = {
    "up":       0x26,   # VK_UP
    "down":     0x28,   # VK_DOWN
    "left":     0x25,   # VK_LEFT
    "right":    0x27,   # VK_RIGHT
    "cross":    0x5A,   # Z  — confirm / select
    "circle":   0x58,   # X  — back / cancel
    "triangle": 0x43,   # C
    "square":   0x56,   # V
    "start":    0x0D,   # Return / Enter
    "select":   0x08,   # Back / Backspace
    "l1":       0x51,   # Q
    "l2":       0x57,   # W
    "r1":       0x45,   # E
    "r2":       0x52,   # R
    # emulator hotkeys
    "f1":       0x70,   # save state to slot
    "f2":       0x71,   # next save slot
    "f3":       0x72,   # load state from slot
    "f10":      0x79,   # reload texture replacements (needs ini hotkey)
}


# ── Win32 INPUT structure ─────────────────────────────────────────────────────
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         W.WORD),
        ("wScan",       W.WORD),
        ("dwFlags",     W.DWORD),
        ("time",        W.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 28)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", W.DWORD), ("_u", _INPUT_UNION)]


def _make_key_input(vk: int, keyup: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if keyup else 0
    if vk in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._u.ki.wVk     = vk
    inp._u.ki.wScan   = 0
    inp._u.ki.dwFlags = flags
    inp._u.ki.time    = 0
    inp._u.ki.dwExtraInfo = 0
    return inp


def _find_pcsx2_hwnd() -> int:
    results = []
    def cb(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if "ESPN NBA 2K5" in title or "PCSX2" in title:
            results.append((hwnd, title))
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    for hwnd, title in results:
        if "ESPN NBA 2K5" in title:
            return hwnd
    return results[0][0] if results else 0


def _focus_pcsx2():
    hwnd = _find_pcsx2_hwnd()
    if not hwnd:
        raise RuntimeError("PCSX2 window not found")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.08)   # let the OS actually transfer focus
    return hwnd


def press(button: str, hold_ms: int = 80):
    """Press and release a PS2 controller button."""
    vk = VK[button.lower()]
    _focus_pcsx2()
    down = _make_key_input(vk, keyup=False)
    up   = _make_key_input(vk, keyup=True)
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(hold_ms / 1000)
    user32.SendInput(1, ctypes.byref(up),   ctypes.sizeof(INPUT))
    time.sleep(0.05)


def tap(button: str):
    press(button, hold_ms=80)


def hold(button: str, duration_ms: int = 500):
    press(button, hold_ms=duration_ms)


def navigate(sequence: str, delay: float = 0.25):
    """
    Send a sequence of button presses, e.g.:
      navigate("left left left cross")
      navigate("up down circle start")
    Tokens: up down left right cross circle triangle square start select l1 l2 r1 r2
    """
    _focus_pcsx2()   # focus once at the start, stay focused
    tokens = sequence.lower().split()
    for token in tokens:
        if token not in VK:
            print(f"  [navigate] unknown: {token!r}")
            continue
        vk   = VK[token]
        down = _make_key_input(vk, keyup=False)
        up   = _make_key_input(vk, keyup=True)
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
        time.sleep(0.08)
        user32.SendInput(1, ctypes.byref(up),   ctypes.sizeof(INPUT))
        time.sleep(delay)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        seq = " ".join(sys.argv[1:])
        print(f"Sending: {seq}")
        navigate(seq)
    else:
        print("Usage: python pcsx2_controller.py <button> [<button> ...]")
        print("Buttons:", ", ".join(VK.keys()))
