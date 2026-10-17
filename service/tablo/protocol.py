"""Device protocol: binary frame format and JSON messages (tablo-software.md §3)."""

import struct
import zlib
from dataclasses import dataclass

WIDTH = 800
HEIGHT = 480
ROW_BYTES = WIDTH // 8
PAYLOAD_SIZE = ROW_BYTES * HEIGHT  # 48 000

MAGIC = b"TBLF"
VERSION = 1
KIND_BASE = 0
KIND_OVERLAY = 1

# magic, version, kind, ttl_s, frame_id, crc32, width, height
_HEADER = struct.Struct("<4sBBHIIHH")
HEADER_SIZE = _HEADER.size  # 20

# Zones the firmware draws itself; the service leaves them white (§2).
FIRMWARE_ZONES = {
    "clock": (0, 0, 184, 100),
    "status": (600, 0, 200, 24),
}
BUTTONS_ZONE = (0, 428, 800, 52)
TILE_WIDTH = 100


@dataclass(frozen=True)
class Frame:
    kind: int
    ttl_s: int
    frame_id: int
    payload: bytes

    @property
    def crc(self) -> int:
        return payload_crc(self.payload)


def payload_crc(payload: bytes) -> int:
    return zlib.crc32(payload) & 0xFFFFFFFF


def encode_frame(frame: Frame) -> bytes:
    if len(frame.payload) != PAYLOAD_SIZE:
        raise ValueError(f"payload must be {PAYLOAD_SIZE} bytes, got {len(frame.payload)}")
    header = _HEADER.pack(
        MAGIC, VERSION, frame.kind, frame.ttl_s, frame.frame_id, frame.crc, WIDTH, HEIGHT
    )
    return header + frame.payload


def decode_frame(data: bytes) -> Frame:
    if len(data) != HEADER_SIZE + PAYLOAD_SIZE:
        raise ValueError(f"bad frame size {len(data)}")
    magic, version, kind, ttl_s, frame_id, crc, width, height = _HEADER.unpack_from(data)
    if magic != MAGIC or version != VERSION:
        raise ValueError("bad magic or version")
    if (width, height) != (WIDTH, HEIGHT):
        raise ValueError(f"bad size {width}x{height}")
    payload = data[HEADER_SIZE:]
    if payload_crc(payload) != crc:
        raise ValueError("crc mismatch")
    return Frame(kind=kind, ttl_s=ttl_s, frame_id=frame_id, payload=payload)


def zones_message() -> dict:
    x, y, w, h = BUTTONS_ZONE
    return {
        **{name: list(rect) for name, rect in FIRMWARE_ZONES.items()},
        "buttons": [x, y, w, h],
        "tile_width": TILE_WIDTH,
    }
