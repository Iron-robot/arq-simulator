"""Packets and checksums.

Each packet carries a CRC-32 checksum over its header and payload. When the
channel corrupts a packet it flips one bit but leaves the checksum alone, so
the receiver detects the damage exactly the way a real NIC would: recompute
the checksum and compare.
"""

from __future__ import annotations

import random
import struct
import zlib
from dataclasses import dataclass, replace

_HEADER = struct.Struct("!I?")  # sequence number (uint32) + is_ack flag


def compute_checksum(seq: int, is_ack: bool, payload: bytes) -> int:
    return zlib.crc32(_HEADER.pack(seq, is_ack) + payload)


@dataclass(frozen=True)
class Packet:
    seq: int
    payload: bytes = b""
    is_ack: bool = False
    checksum: int = 0

    @classmethod
    def data(cls, seq: int, payload: bytes) -> "Packet":
        return cls(seq=seq, payload=payload, is_ack=False,
                   checksum=compute_checksum(seq, False, payload))

    @classmethod
    def ack(cls, seq: int) -> "Packet":
        return cls(seq=seq, payload=b"", is_ack=True,
                   checksum=compute_checksum(seq, True, b""))

    def is_valid(self) -> bool:
        """True if the checksum still matches the contents."""
        return self.checksum == compute_checksum(self.seq, self.is_ack, self.payload)

    def corrupted(self, rng: random.Random) -> "Packet":
        """Return a copy with one random bit flipped in the seq field or payload.

        CRC-32 is guaranteed to detect every single-bit error, so a corrupted
        packet always fails `is_valid()`.
        """
        total_bits = 32 + 8 * len(self.payload)
        bit = rng.randrange(total_bits)
        if bit < 32:
            return replace(self, seq=self.seq ^ (1 << bit))
        bit -= 32
        data = bytearray(self.payload)
        data[bit // 8] ^= 1 << (bit % 8)
        return replace(self, payload=bytes(data))

    def __str__(self) -> str:
        kind = "ACK" if self.is_ack else "DATA"
        return f"{kind}(seq={self.seq})"
