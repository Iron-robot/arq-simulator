"""Shared plumbing for every ARQ protocol.

Each protocol subclass only has to describe the parts that differ:
  * how the sender reacts to ACKs and timeouts
  * how the receiver reacts to data packets
  * which window / sequence-number sizes are legal

Sequence numbers
----------------
Internally the sender and receiver count packets with ordinary integers
(0, 1, 2, ... num_packets-1), called *absolute* indices. Only the value
`index % 2**seq_bits` goes into the packet header, exactly like a real
k-bit header field that wraps around. Converting a wire sequence number back
to an absolute index is where the window-size rules matter: it is only
unambiguous when the window is small enough relative to the sequence space.
"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from typing import List, Optional

from arq.channel import Channel
from arq.config import SimConfig
from arq.events import Event, EventScheduler
from arq.metrics import Counters, RunResult
from arq.packet import Packet


def make_payload(index: int) -> bytes:
    """The content of data packet number `index` (what the app is sending)."""
    return f"packet-{index:06d}".encode()


class ARQProtocol(ABC):
    name: str = "base"
    key: str = "base"

    def __init__(self, config: SimConfig) -> None:
        config.validate()
        self.cfg = config
        self.n = config.num_packets
        self.window = self.effective_window(config.window_size)
        self.seq_bits = config.seq_bits if config.seq_bits is not None else self.default_seq_bits(self.window)
        self.seq_mod = 2 ** self.seq_bits
        self.check_seq_space()

        self.timeout = config.timeout if config.timeout is not None else self.default_timeout()
        self.scheduler = EventScheduler()
        self.rng = random.Random(config.seed)
        self.counters = Counters()
        self.channel = Channel(config.channel, self.scheduler, self.rng, self.counters,
                               config.tx_time, self.log if config.verbose else None)

        self.delivered: List[bytes] = []   # what the receiver handed to the application, in order
        self._ever_sent: set[int] = set()
        self.finish_time: Optional[float] = None
        self.setup()

    # ---- rules each protocol defines -------------------------------------

    def effective_window(self, requested: int) -> int:
        return requested

    @abstractmethod
    def default_seq_bits(self, window: int) -> int: ...

    @abstractmethod
    def check_seq_space(self) -> None:
        """Raise ValueError if window and sequence space are incompatible."""

    @abstractmethod
    def setup(self) -> None: ...

    @abstractmethod
    def start(self) -> None:
        """Send the first packet(s)."""

    @abstractmethod
    def sender_done(self) -> bool: ...

    @abstractmethod
    def on_data(self, packet: Packet) -> None:
        """Receiver side: a data packet with a valid checksum arrived."""

    @abstractmethod
    def on_ack(self, packet: Packet) -> None:
        """Sender side: an ACK with a valid checksum arrived."""

    # ---- defaults --------------------------------------------------------

    def default_timeout(self) -> float:
        """A timeout comfortably longer than the worst-case round trip.

        Worst case for the packet at the back of a full window:
        wait for the window ahead of it to be transmitted, transmit it,
        travel there, ACK travels back (each leg up to delay + jitter).
        """
        c = self.cfg.channel
        rtt = self.cfg.tx_time + 2 * (c.delay + c.jitter)
        return 1.5 * rtt + self.window * self.cfg.tx_time

    @staticmethod
    def bits_for(values_needed: int) -> int:
        """Smallest k with 2**k >= values_needed (at least 1)."""
        return max(1, math.ceil(math.log2(values_needed)))

    # ---- helpers protocols call -----------------------------------------

    def log(self, message: str) -> None:
        if self.cfg.verbose:
            print(f"[{self.scheduler.now:10.2f} ms] {message}")

    def wire_seq(self, index: int) -> int:
        return index % self.seq_mod

    def send_data(self, index: int) -> float:
        """Transmit data packet `index`. Returns when it finished leaving the sender."""
        packet = Packet.data(self.wire_seq(index), make_payload(index))
        self.counters.data_sent += 1
        if index in self._ever_sent:
            self.counters.retransmissions += 1
            self.log(f"SENDER   retransmit {packet} (packet #{index})")
        else:
            self._ever_sent.add(index)
            self.log(f"SENDER   send       {packet} (packet #{index})")
        return self.channel.send(packet, self._data_arrived)

    def send_ack(self, seq: int) -> None:
        self.counters.acks_sent += 1
        self.log(f"RECEIVER send ACK(seq={seq})")
        self.channel.send(Packet.ack(seq), self._ack_arrived)

    def deliver(self, payload: bytes) -> None:
        """Hand a packet to the application layer (must happen in order, once)."""
        self.delivered.append(payload)
        self.log(f"RECEIVER deliver    {payload.decode(errors='replace')} to application")

    def start_timer(self, departed_at: float, callback, *args) -> Event:
        """Start a retransmission timer that expires `timeout` ms after the
        packet finished leaving the sender."""
        start = max(departed_at, self.scheduler.now)
        return self.scheduler.schedule(start - self.scheduler.now + self.timeout, callback, *args)

    def mark_finished_if_done(self) -> None:
        if self.finish_time is None and self.sender_done():
            self.finish_time = self.scheduler.now
            self.log("SENDER   all packets acknowledged - done")

    # ---- channel callbacks ----------------------------------------------

    def _data_arrived(self, packet: Packet) -> None:
        if not packet.is_valid():
            self.log(f"RECEIVER got corrupted packet - checksum mismatch, discarded")
            return
        self.log(f"RECEIVER got        {packet}")
        self.on_data(packet)

    def _ack_arrived(self, packet: Packet) -> None:
        if not packet.is_valid():
            self.log("SENDER   got corrupted ACK - checksum mismatch, discarded")
            return
        self.log(f"SENDER   got        {packet}")
        self.on_ack(packet)
        self.mark_finished_if_done()

    # ---- run ------------------------------------------------------------

    def run(self) -> RunResult:
        self.log(f"=== {self.name}: {self.n} packets, window={self.window}, "
                 f"seq_bits={self.seq_bits}, timeout={self.timeout:.2f} ms ===")
        self.start()
        completed = self.scheduler.run(stop_when=self.sender_done, max_time=self.cfg.max_time)
        end = self.finish_time if self.finish_time is not None else self.scheduler.now
        return RunResult(
            protocol=self.name,
            num_packets=self.n,
            window_size=self.window,
            seq_bits=self.seq_bits,
            timeout=self.timeout,
            delivered=len(self.delivered),
            completed=completed,
            total_time_ms=end,
            packet_size=self.cfg.packet_size,
            tx_time=self.cfg.tx_time,
            counters=self.counters,
        )
