import gzip
import pytest
from welcome_assistant.protocol import decode_frame, fields


def vi(n):
    result = bytearray()
    while n > 127:
        result.append((n & 127) | 128)
        n >>= 7
    result.append(n)
    return bytes(result)


def f(k, value):
    if isinstance(value, int):
        return vi(k << 3) + vi(value)
    if isinstance(value, str):
        value = value.encode()
    return vi(k << 3 | 2) + vi(len(value)) + value


def frame(method="WebcastMemberMessage", action=0, compressed=True):
    user = f(1, 123456) + f(3, "小明🌟")
    common = f(2, 456) + f(4, 1700000000)
    member = f(1, common) + f(2, user) + f(10, action)
    message = f(1, method) + f(2, member) + f(3, 789)
    response = f(1, message)
    return f(8, gzip.compress(response) if compressed else response)


@pytest.mark.parametrize("compressed", [True, False])
def test_member_with_id_and_timestamp(compressed):
    result = decode_frame(frame(compressed=compressed))
    assert len(result) == 1
    assert result[0].nickname == "小明🌟"
    assert result[0].user_id == "123456"
    assert result[0].event_id == "789"
    assert result[0].created_at == 1700000000


def test_not_chat_or_admin():
    assert decode_frame(frame(method="WebcastChatMessage")) == []
    assert len(decode_frame(frame(action=1))) == 1
    assert decode_frame(frame(action=2)) == []


@pytest.mark.parametrize("payload", [b"\x00", b"\x0a\x7fshort", b"\x08\x80", b"\x0f", b"\x80" * 11])
def test_malformed_rejected(payload):
    with pytest.raises(ValueError):
        fields(payload)


def test_gzip_bomb_bounded():
    with pytest.raises(ValueError):
        decode_frame(f(8, gzip.compress(b"x" * (5 * 1024 * 1024))))
