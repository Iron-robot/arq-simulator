"""Stop-and-Wait ARQ.

The simplest reliable protocol: send ONE packet, then wait.
  * If its ACK comes back -> send the next packet.
  * If the timer runs out first -> send the same packet again.

A 1-bit sequence number (0, 1, 0, 1, ...) is enough. It lets the receiver
tell a brand-new packet from a retransmission of one it already delivered
(which happens when the packet arrived but its ACK was lost).
"""

from __future__ import annotations

from typing import Optional

from arq.events import Event
from arq.packet import Packet
from arq.protocols.base import ARQProtocol


class StopAndWait(ARQProtocol):
    name = "Stop-and-Wait"
    key = "sw"

    def effective_window(self, requested: int) -> int:
        return 1  # by definition: only one packet in flight

    def default_seq_bits(self, window: int) -> int:
        return 1

    def check_seq_space(self) -> None:
        if self.seq_mod < 2:
            raise ValueError("Stop-and-Wait needs at least 2 sequence numbers (seq_bits >= 1)")

    def setup(self) -> None:
        # sender
        self.current = 0                   # absolute index of the packet we are waiting on
        self.timer: Optional[Event] = None
        # receiver
        self.expected = 0                  # absolute index of the next packet to deliver

    # ---- sender ----------------------------------------------------------

    def start(self) -> None:
        self._transmit_current()

    def sender_done(self) -> bool:
        return self.current >= self.n

    def _transmit_current(self) -> None:
        departed = self.send_data(self.current)
        self.timer = self.start_timer(departed, self._on_timeout)

    def _on_timeout(self) -> None:
        self.counters.timeouts += 1
        self.log(f"SENDER   TIMEOUT waiting for ACK(seq={self.wire_seq(self.current)})")
        self._transmit_current()

    def on_ack(self, packet: Packet) -> None:
        if packet.seq != self.wire_seq(self.current):
            return  # an old, duplicate ACK - ignore it
        self.timer.cancel()
        self.current += 1
        if self.current < self.n:
            self._transmit_current()

    # ---- receiver --------------------------------------------------------

    def on_data(self, packet: Packet) -> None:
        if packet.seq == self.wire_seq(self.expected):
            self.deliver(packet.payload)
            self.expected += 1
        else:
            # Same seq as last time: our ACK was lost and the sender retried.
            self.counters.duplicates_discarded += 1
        # ACK it either way, so the sender can move on.
        self.send_ack(packet.seq)
