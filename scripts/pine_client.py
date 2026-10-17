"""
pine_client.py — PCSX2 PINE IPC protocol client

Empirically verified PINE protocol (PCSX2 Qt, TCP port 28011):
  Request:  [uint32_le total_size] [uint8 cmd] [args...]
            NO terminator byte needed — size field delimits the message.
  Response: [uint32_le reply_size] [uint8 status=0x00 ok / 0xFF error] [result...]

Read commands return:  status(1) + value(N)
Write commands return: status(1)            (no value)
Meta commands (Title, ID, Status) return 0xFF when game is in demo/attract mode.

Commands:
  0x00 Read8   [uint32 addr] -> [uint8]
  0x01 Read16  [uint32 addr] -> [uint16]
  0x02 Read32  [uint32 addr] -> [uint32]
  0x03 Read64  [uint32 addr] -> [uint64]
  0x08 Write8  [uint32 addr][uint8]
  0x09 Write16 [uint32 addr][uint16]
  0x0A Write32 [uint32 addr][uint32]
  0x13 Title   -> [null-terminated string]  (may fail in demo mode)
  0x14 ID      -> [null-terminated string]  (may fail in demo mode)
  0x17 Status  -> [uint32]                  (may fail in demo mode)
"""

import socket
import struct
import time
from typing import Optional

PINE_HOST = "127.0.0.1"
PINE_PORT = 28011

# PS2 EE RAM: 32 MB @ 0x00000000
EE_RAM_BASE = 0x00000000
EE_RAM_SIZE = 0x02000000  # 32 MB

CMD_READ8   = 0x00
CMD_READ16  = 0x01
CMD_READ32  = 0x02
CMD_READ64  = 0x03
CMD_WRITE8  = 0x08
CMD_WRITE16 = 0x09
CMD_WRITE32 = 0x0A
CMD_TITLE   = 0x13
CMD_ID      = 0x14
CMD_UUID    = 0x15
CMD_STATUS  = 0x17

_READ_SIZES  = {CMD_READ8: 1, CMD_READ16: 2, CMD_READ32: 4, CMD_READ64: 8}
_WRITE_CMDS  = {CMD_WRITE8, CMD_WRITE16, CMD_WRITE32}


class PineClient:
    def __init__(self, host=PINE_HOST, port=PINE_PORT):
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self.host, self.port))
        self._sock.settimeout(5.0)

    def close(self):
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    # ── low-level ────────────────────────────────────────────────────────────

    def _send(self, cmd_bytes: bytes) -> bytes:
        """Send one command, return full response bytes (including 4-byte size prefix)."""
        msg = struct.pack("<I", 4 + len(cmd_bytes)) + cmd_bytes
        self._sock.sendall(msg)
        # read reply size
        raw = b""
        while len(raw) < 4:
            raw += self._sock.recv(4 - len(raw))
        reply_size = struct.unpack_from("<I", raw)[0]
        body_size  = reply_size - 4
        body = b""
        while len(body) < body_size:
            chunk = self._sock.recv(body_size - len(body))
            if not chunk:
                raise ConnectionError("PINE connection closed")
            body += chunk
        return raw + body  # full reply including size prefix

    def _check(self, reply: bytes) -> bytes:
        """Assert status byte == 0x00 and return payload after it."""
        status = reply[4]
        if status == 0xFF:
            raise RuntimeError("PINE IPC_FAIL (0xFF) — command not supported in current game state")
        if status != 0x00:
            raise RuntimeError(f"PINE unexpected status byte: {status:#04x}")
        return reply[5:]

    # ── single operations ────────────────────────────────────────────────────

    def _read_n(self, cmd: int, addr: int) -> int:
        size  = _READ_SIZES[cmd]
        reply = self._send(struct.pack("<BI", cmd, addr))
        data  = self._check(reply)
        fmts  = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}
        return struct.unpack_from(fmts[size], data)[0]

    def read8(self, addr: int) -> int:   return self._read_n(CMD_READ8,  addr)
    def read16(self, addr: int) -> int:  return self._read_n(CMD_READ16, addr)
    def read32(self, addr: int) -> int:  return self._read_n(CMD_READ32, addr)

    def write8(self, addr: int, value: int):
        reply = self._send(struct.pack("<BIB",  CMD_WRITE8,  addr, value & 0xFF))
        self._check(reply)

    def write16(self, addr: int, value: int):
        reply = self._send(struct.pack("<BIH", CMD_WRITE16, addr, value & 0xFFFF))
        self._check(reply)

    def write32(self, addr: int, value: int):
        reply = self._send(struct.pack("<BII", CMD_WRITE32, addr, value & 0xFFFFFFFF))
        self._check(reply)

    # ── bulk read/write ───────────────────────────────────────────────────────

    def read_bytes(self, addr: int, length: int) -> bytes:
        """Read a contiguous block of PS2 RAM. Uses Read32 where possible for speed."""
        result = bytearray()
        offset = 0
        # Read in 4-byte chunks where aligned
        while offset + 4 <= length:
            val = self.read32(addr + offset)
            result += struct.pack("<I", val)
            offset += 4
        # Trailing bytes
        while offset < length:
            result.append(self.read8(addr + offset))
            offset += 1
        return bytes(result)

    def write_bytes(self, addr: int, data: bytes):
        """Write a block of bytes to PS2 RAM."""
        for i, b in enumerate(data):
            self.write8(addr + i, b)

    # ── metadata ─────────────────────────────────────────────────────────────

    def _read_meta_string(self, cmd: int) -> str:
        reply = self._send(bytes([cmd]))
        data  = self._check(reply)
        end   = data.find(b"\x00")
        return data[:end].decode("ascii", errors="replace") if end >= 0 else data.decode("ascii", errors="replace")

    def title(self) -> str:   return self._read_meta_string(CMD_TITLE)
    def game_id(self) -> str: return self._read_meta_string(CMD_ID)

    def status(self) -> str:
        reply = self._send(bytes([CMD_STATUS]))
        data  = self._check(reply)
        code  = struct.unpack_from("<I", data)[0]
        return {0: "Running", 1: "Paused", 2: "Shutdown"}.get(code, f"Unknown({code})")

    # ── scan ─────────────────────────────────────────────────────────────────

    def scan_string(self, needle: bytes, start: int = EE_RAM_BASE,
                    end: int = EE_RAM_BASE + EE_RAM_SIZE,
                    block: int = 0x8000, verbose: bool = True) -> list[int]:
        """
        Scan PS2 EE RAM for a byte sequence using Read32-based bulk reads.
        block: bytes per iteration (must be multiple of 4).
        """
        hits  = []
        addr  = start
        carry = b""  # overlap from previous block for cross-boundary matches
        overlap = len(needle) - 1

        while addr < end:
            size = min(block, end - addr)
            if verbose:
                pct = 100 * (addr - start) / (end - start)
                print(f"\r  scanning {addr:#010x}  ({pct:.0f}%) ...", end="", flush=True)
            try:
                data = carry + self.read_bytes(addr, size)
                pos  = 0
                while True:
                    idx = data.find(needle, pos)
                    if idx == -1:
                        break
                    abs_addr = addr + idx - len(carry)
                    hits.append(abs_addr)
                    pos = idx + 1
                carry = data[-overlap:] if overlap > 0 else b""
            except Exception as e:
                if verbose:
                    print(f"\n  read error at {addr:#010x}: {e}")
                carry = b""
            addr += size

        if verbose:
            print(f"\r  scan done — {len(hits)} hit(s)                              ")
        return hits


# ── convenience ───────────────────────────────────────────────────────────────

def quick_info():
    with PineClient() as p:
        print(f"Status : {p.status()}")
        print(f"Title  : {p.title()}")
        print(f"Game ID: {p.game_id()}")


if __name__ == "__main__":
    quick_info()
