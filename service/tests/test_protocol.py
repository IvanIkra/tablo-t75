import pytest

from tablo import protocol
from tablo.render.canvas import Canvas, pack, unpack


def test_frame_roundtrip():
    payload = bytes(range(256)) * (protocol.PAYLOAD_SIZE // 256) + bytes(protocol.PAYLOAD_SIZE % 256)
    frame = protocol.Frame(protocol.KIND_OVERLAY, 20, 7, payload)
    data = protocol.encode_frame(frame)
    assert len(data) == protocol.HEADER_SIZE + protocol.PAYLOAD_SIZE == 48_020
    assert data[:4] == b"TBLF"
    assert protocol.decode_frame(data) == frame


def test_decode_rejects_corrupted_payload():
    frame = protocol.Frame(protocol.KIND_BASE, 0, 1, bytes(protocol.PAYLOAD_SIZE))
    data = bytearray(protocol.encode_frame(frame))
    data[-1] ^= 1
    with pytest.raises(ValueError, match="crc"):
        protocol.decode_frame(bytes(data))


def test_pack_bit_order_and_polarity():
    c = Canvas()
    c.image.putpixel((0, 0), 0)  # black, top-left
    c.image.putpixel((9, 0), 0)  # black, second byte, second bit
    payload = pack(c.to_bw())
    assert payload[0] == 0b1000_0000
    assert payload[1] == 0b0100_0000
    assert payload[2:] == bytes(protocol.PAYLOAD_SIZE - 2)  # white is 0
    assert unpack(payload).getpixel((9, 0)) == 0
