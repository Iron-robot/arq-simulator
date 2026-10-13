"""Go-Back-N ARQ.

The sender may have up to N un-ACKed packets "in flight" (the window).

Sender
  * Keeps ONE timer, for the oldest un-ACKed packet (`base`).
  * ACKs are cumulative: ACK(k) means "I have everything up to and including k".
  * On timeout it "goes back": resends EVERY packet from `base` onward.

Receiver
  * Has no buffer. It only accepts the exact packet it expects next.
  * Anything else (a gap, a duplicate) is thrown away, and the receiver
    re-sends the ACK for the last in-order packet it got.

Rule: window N must be smaller than the sequence space, N <= 2^k - 1.
Otherwise a cumulative ACK could mean two different things.
"""

from __future__ import annotations

from typing import Dict, Optional

from arq.events import Event
from arq.packet import Packet
from arq.protocols.base import ARQProtocol


class GoBackN(ARQProtocol):
    name = "Go-Back-N"
    key = "gbn"

    def default_seq_bits(self, window: int) -> int:
        return max(3, self.bits_for(window + 1))

    def check_seq_space(self) -> None:
        if self.window >= self.seq_mod:
            raise ValueError(
                f"Go-Back-N needs window < 2^seq_bits; window={self.window}, "
                f"2^{self.seq_bits}={self.seq_mod}. Use seq_bits >= {self.bits_for(self.window + 1)}."
            )

    def setup(self) -> None:
        # sender
        self.base = 0                       # oldest un-ACKed packet
        self.next_index = 0                 # next new packet to send
        self.timer: Optional[Event] = None
        self.departed: Dict[int, float] = {}
        # receiver
        self.expected = 0

    # ---- sender ----------------------------------------------------------

    def start(self) -> None:
        self._fill_window()

    def sender_done(self) -> bool:
        return self.base >= self.n

    def _fill_window(self) -> None:
        while self.next_index < self.n and self.next_index < self.base + self.window:
            self.departed[self.next_index] = self.send_data(self.next_index)
            self.next_index += 1
        if self.timer is None and self.base < self.next_index:
            self.timer = self.start_timer(self.departed[self.base], self._on_timeout)

    def _on_timeout(self) -> None:
        self.counters.timeouts += 1
        self.log(f"SENDER   TIMEOUT - going back to packet #{self.base}, "
                 f"resending {self.next_index - self.base} packet(s)")
        for index in range(self.base, self.next_index):
            self.departed[index] = self.send_data(index)
        self.timer = self.start_timer(self.departed[self.base], self._on_timeout)

    def on_ack(self, packet: Packet) -> None:
        # Which in-flight packet does this wire seq number refer to?
        offset = (packet.seq - self.base) % self.seq_mod
        if offset >= self.next_index - self.base:
            return  # ACK for something already ACKed (a duplicate) - ignore
        self.base += offset + 1            # cumulative: everything up to here is confirmed
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        self._fill_window()                # slides the window and restarts the timer if needed

    # ---- receiver --------------------------------------------------------

    def on_data(self, packet: Packet) -> None:
        if packet.seq == self.wire_seq(self.expected):
            self.deliver(packet.payload)
            self.expected += 1
            self.send_ack(packet.seq)
        else:
            self.counters.duplicates_discarded += 1
            # Re-ACK the last packet received in order (seq of expected - 1).
            self.send_ack(self.wire_seq(self.expected - 1))
