"""Selective Repeat ARQ.

Like Go-Back-N, the sender keeps up to N packets in flight - but each one is
handled individually.

Sender
  * One timer PER packet.
  * ACKs are individual: ACK(k) confirms only packet k.
  * On timeout it resends ONLY the packet whose timer expired.
  * The window slides forward past every packet that is ACKed, in order.

Receiver
  * Has a buffer the size of the window. Packets that arrive early (after a
    gap) are stored, not thrown away, and ACKed right away.
  * When the missing packet finally arrives, it and every buffered packet
    behind it are delivered to the application in order.
  * A packet from the *previous* window means our ACK was lost: re-ACK it.

Rule: window N must be at most half the sequence space, N <= 2^(k-1).
Otherwise a retransmitted old packet looks identical to a new one.
"""

from __future__ import annotations

from typing import Dict, List

from arq.events import Event
from arq.packet import Packet
from arq.protocols.base import ARQProtocol


class SelectiveRepeat(ARQProtocol):
    name = "Selective Repeat"
    key = "sr"

    def default_seq_bits(self, window: int) -> int:
        return max(3, self.bits_for(2 * window))

    def check_seq_space(self) -> None:
        if 2 * self.window > self.seq_mod:
            raise ValueError(
                f"Selective Repeat needs window <= 2^(seq_bits-1); window={self.window}, "
                f"2^{self.seq_bits}={self.seq_mod}. Use seq_bits >= {self.bits_for(2 * self.window)}."
            )

    def setup(self) -> None:
        # sender
        self.base = 0
        self.next_index = 0
        self.acked: List[bool] = [False] * self.n
        self.timers: Dict[int, Event] = {}
        # receiver
        self.rcv_base = 0
        self.buffer: Dict[int, bytes] = {}   # absolute index -> payload, waiting for a gap to fill

    # ---- sender ----------------------------------------------------------

    def start(self) -> None:
        self._fill_window()

    def sender_done(self) -> bool:
        return self.base >= self.n

    def _fill_window(self) -> None:
        while self.next_index < self.n and self.next_index < self.base + self.window:
            self._transmit(self.next_index)
            self.next_index += 1

    def _transmit(self, index: int) -> None:
        departed = self.send_data(index)
        self.timers[index] = self.start_timer(departed, self._on_timeout, index)

    def _on_timeout(self, index: int) -> None:
        self.counters.timeouts += 1
        self.log(f"SENDER   TIMEOUT for packet #{index} - resending only that one")
        self._transmit(index)

    def on_ack(self, packet: Packet) -> None:
        offset = (packet.seq - self.base) % self.seq_mod
        if offset >= self.next_index - self.base:
            return  # not in the current window: a late duplicate ACK
        index = self.base + offset
        if self.acked[index]:
            return
        self.acked[index] = True
        self.timers.pop(index).cancel()
        while self.base < self.next_index and self.acked[self.base]:
            self.base += 1
        self._fill_window()

    # ---- receiver --------------------------------------------------------

    def on_data(self, packet: Packet) -> None:
        offset = (packet.seq - self.rcv_base) % self.seq_mod
        if offset < self.window:
            # Inside the receive window: ACK it and buffer it.
            index = self.rcv_base + offset
            self.send_ack(packet.seq)
            if index in self.buffer:
                self.counters.duplicates_discarded += 1
                return
            self.buffer[index] = packet.payload
            if index != self.rcv_base:
                self.counters.out_of_order_buffered += 1
                self.log(f"RECEIVER buffer     packet #{index} (waiting for #{self.rcv_base})")
            # Deliver the longest in-order run starting at rcv_base.
            while self.rcv_base in self.buffer:
                self.deliver(self.buffer.pop(self.rcv_base))
                self.rcv_base += 1
        elif offset >= self.seq_mod - self.window:
            # From the previous window: already delivered, but the sender
            # never got our ACK. Re-ACK so it can move on.
            self.counters.duplicates_discarded += 1
            self.send_ack(packet.seq)
        else:
            self.counters.duplicates_discarded += 1  # cannot happen on a FIFO link; ignore
