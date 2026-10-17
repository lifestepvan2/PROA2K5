"""
pcsx2_capture.py — screenshot and window utilities for PCSX2

Usage:
    python scripts/pcsx2_capture.py              # single screenshot → docs/pcsx2_screen.png
    python scripts/pcsx2_capture.py --watch 2    # screenshot every 2 seconds
    python scripts/pcsx2_capture.py --f8         # trigger PCSX2's built-in F8 snapshot too
"""

import ctypes
import ctypes.wintypes as W
import subprocess
import sys
import time
from pathlib import Path

# ── Win32 helpers ────────────────────────────────────────────────────────────
user32   = ctypes.windll.user32
gdi32    = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

SRCCOPY  = 0x00CC0020


class RECT(ctypes.Structure):
    _fields_ = [("left", W.LONG), ("top", W.LONG), ("right", W.LONG), ("bottom", W.LONG)]


def _find_pcsx2_hwnd():
    results = []

    def enum_cb(hwnd, _):
        length  = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if "ESPN NBA 2K5" in title or "PCSX2" in title:
            results.append((hwnd, title))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    # Prefer the game window; fall back to main PCSX2 frame
    for hwnd, title in results:
        if "ESPN NBA 2K5" in title:
            return hwnd, title
    if results:
        return results[0]
    return None, None


def capture(out_path: Path) -> bool:
    """Capture the PCSX2/game window via BitBlt and save as PNG."""
    hwnd, title = _find_pcsx2_hwnd()
    if hwnd is None:
        print("ERROR: PCSX2 window not found.")
        return False

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right  - rect.left
    h = rect.bottom - rect.top

    # Use screen DC + BitBlt (works for hardware-accelerated GL/DX windows too)
    screen_dc = user32.GetDC(0)
    mem_dc    = gdi32.CreateCompatibleDC(screen_dc)
    bitmap    = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old_bmp   = gdi32.SelectObject(mem_dc, bitmap)

    gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, rect.left, rect.top, SRCCOPY)

    # Save via PIL if available, otherwise fall back to PowerShell
    try:
        from PIL import Image
        import struct, array

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize",          W.DWORD),
                ("biWidth",         W.LONG),
                ("biHeight",        W.LONG),
                ("biPlanes",        W.WORD),
                ("biBitCount",      W.WORD),
                ("biCompression",   W.DWORD),
                ("biSizeImage",     W.DWORD),
                ("biXPelsPerMeter", W.LONG),
                ("biYPelsPerMeter", W.LONG),
                ("biClrUsed",       W.DWORD),
                ("biClrImportant",  W.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize      = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth     = w
        bmi.biHeight    = -h  # top-down
        bmi.biPlanes    = 1
        bmi.biBitCount  = 32
        bmi.biCompression = 0  # BI_RGB

        buf = (ctypes.c_char * (w * h * 4))()
        gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, ctypes.byref(bmi), 0)

        img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1)
        img.save(str(out_path))
        saved = True
    except ImportError:
        # PowerShell fallback
        ps = f"""
Add-Type -AssemblyName System.Drawing
$bmp = [System.Drawing.Bitmap]::new({w}, {h})
$g   = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen({rect.left}, {rect.top}, 0, 0, [System.Drawing.Size]::new({w}, {h}), [System.Drawing.CopyPixelOperation]::SourceCopy)
$bmp.Save('{out_path}', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"""
        subprocess.run(["powershell", "-Command", ps], check=True)
        saved = True

    # Cleanup GDI handles
    gdi32.SelectObject(mem_dc, old_bmp)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(0, screen_dc)

    if saved:
        size = out_path.stat().st_size
        print(f"Captured '{title}' ({w}x{h}) -> {out_path}  [{size:,} bytes]")
    return saved


def send_key(vk_code: int, delay_ms: int = 80):
    """Send a keydown + keyup to the PCSX2 window (for emulator hotkeys, not PS2 inputs)."""
    hwnd, _ = _find_pcsx2_hwnd()
    if hwnd is None:
        return False
    WM_KEYDOWN = 0x0100
    WM_KEYUP   = 0x0101
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk_code, 0)
    time.sleep(delay_ms / 1000)
    user32.PostMessageW(hwnd, WM_KEYUP, vk_code, 0)
    return True


def trigger_pcsx2_snapshot():
    """Press F8 — PCSX2 built-in screenshot saved to snaps/ folder."""
    VK_F8 = 0x77
    ok = send_key(VK_F8)
    if ok:
        print("F8 sent → PCSX2 will save its own snapshot to snaps/")
    return ok


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PCSX2 screen capture utility")
    parser.add_argument("--out", default="docs/pcsx2_screen.png", help="Output PNG path")
    parser.add_argument("--watch", type=float, default=0, metavar="SECONDS",
                        help="Loop and capture every N seconds")
    parser.add_argument("--f8", action="store_true", help="Also trigger PCSX2 built-in F8 snapshot")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    out_path  = repo_root / args.out

    if args.f8:
        trigger_pcsx2_snapshot()
        time.sleep(0.5)

    if args.watch > 0:
        idx = 0
        while True:
            p = out_path.with_stem(f"{out_path.stem}_{idx:04d}")
            capture(p)
            idx += 1
            time.sleep(args.watch)
    else:
        capture(out_path)
