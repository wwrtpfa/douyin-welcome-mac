"""Bounded, read-only decoder for webcast MemberMessage protobuf fields.

Wire field references are documented in docs/PROTOCOL.md. Unknown fields are
ignored; malformed payloads are rejected, never interpreted as arrival events.
"""
import gzip
import io
from dataclasses import dataclass

LIMIT = 4 * 1024 * 1024


def varint(data: bytes, pos: int):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ValueError("Truncated protobuf varint")
        b = data[pos]
        pos += 1
        value |= (b & 127) << shift
        if b < 128:
            return value, pos
    raise ValueError("Oversized protobuf varint")


def fields(data: bytes) -> dict:
    if len(data) > LIMIT:
        raise ValueError("Payload too large")
    result = {}
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError("Invalid protobuf tag")
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, pos = varint(data, pos)
            else:
                size = 8 if wire == 1 else 4
            if size > len(data) - pos:
                raise ValueError("Truncated protobuf field")
            value = data[pos:pos + size]
            pos += size
        else:
            raise ValueError("Unsupported protobuf wire type")
        result.setdefault(number, []).append(value)
    return result


def first(data, key, default=b""):
    return data.get(key, [default])[0]


def string(data, key):
    value = first(data, key)
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else ""


@dataclass(frozen=True)
class Arrival:
    user_id: str
    nickname: str
    event_id: str = ""
    created_at: int = 0


def decode_frame(frame: bytes) -> list[Arrival]:
    envelope = fields(frame)
    payload = first(envelope, 8)
    if not isinstance(payload, bytes) or not payload:
        return []
    if payload.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
            payload = compressed.read(LIMIT + 1)
    response = fields(payload)
    arrivals = []
    for raw_message in response.get(1, []):
        message = fields(raw_message)
        if string(message, 1) != "WebcastMemberMessage":
            continue
        member = fields(first(message, 2))
        # Observed schemas use absent/0 or 1 for normal arrivals. Other actions
        # are not guessed to be arrivals; this needs live-room verification.
        if first(member, 5, 0) or first(member, 10, 0) not in (0, 1):
            continue
        user = fields(first(member, 2))
        common = fields(first(member, 1))
        uid = string(user, 1028) or str(first(user, 1, 0) or first(member, 12, 0))
        nickname = string(user, 3).strip()
        if uid != "0" and nickname:
            arrivals.append(Arrival(uid, nickname, str(first(message, 3, 0) or first(common, 2, 0)), int(first(common, 4, 0))))
    return arrivals
