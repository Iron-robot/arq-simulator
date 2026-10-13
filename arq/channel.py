"""The error-simulation engine: an unreliable, one-hop network link.

For every packet the channel decides, using its own random generator:
  1. Is it lost?       (loss_rate for data, ack_loss_rate for ACKs)
  2. Is it corrupted?  (corrupt_rate; one bit flipped, checksum left as-is)
  3. How late is it?   (delay + uniform random jitter)

Timing model
------------
* Data packets take `tx_time` ms to be pushed onto the wire, one at a time
  (the sender has a single outgoing link). ACKs are tiny, so their
  transmission time is treated as zero.
* After leaving, a packet travels for `delay + jitter` ms.
* The link is FIFO: jitter can make a packet slower, but never lets it
  overtake one sent earlier in the same direction. Packets can be lost,
  but not reordered - the same assumption the textbook sequence-number
  rules (N < 2^k for GBN, N <= 2^(k-1) for SR) are built on.
"""

from __future__ import annotations

import random
from typing import Callable, Dict, Optional

from arq.config import ChannelConfig
from arq.events import EventScheduler
from arq.metrics import Counters
from arq.packet import Packet

Logger = Callable[[str], None]


class Channel:
    def __init__(
        self,
        config: ChannelConfig,
        scheduler: EventScheduler,
        rng: random.Random,
        counters: Counters,
        tx_time: float,
        log: Optional[Logger] = None,
    ) -> None:
        self.cfg = config
        self.scheduler = scheduler
        self.rng = rng
        self.counters = counters
        self.tx_time = tx_time
        self.log = log or (lambda _msg: None)
        # Per-direction state: when the link is free again, and the latest arrival time.
        self._link_free_at: Dict[bool, float] = {False: 0.0, True: 0.0}
        self._last_arrival: Dict[bool, float] = {False: 0.0, True: 0.0}

    def send(self, packet: Packet, deliver: Callable[[Packet], None]) -> float:
        """Put `packet` on the link. `deliver(packet)` is called on arrival
        unless the packet is lost.

        Returns the simulated time at which the packet finished leaving the
        sender - protocols start their retransmission timers from this moment.
        """
        is_ack = packet.is_ack
        now = self.scheduler.now
        tx = 0.0 if is_ack else self.tx_time
        start = max(now, self._link_free_at[is_ack])
        departed = start + tx
        self._link_free_at[is_ack] = departed

        loss_rate = self.cfg.ack_loss_rate if is_ack else self.cfg.loss_rate
        if self.rng.random() < loss_rate:
            if is_ack:
                self.counters.acks_lost += 1
            else:
                self.counters.data_lost += 1
            self.log(f"  channel: {packet} LOST")
            return departed

        if self.rng.random() < self.cfg.corrupt_rate:
            packet = packet.corrupted(self.rng)
            if is_ack:
                self.counters.acks_corrupted += 1
            else:
                self.counters.data_corrupted += 1
            self.log(f"  channel: {packet} CORRUPTED in transit")

        jitter = self.rng.uniform(0.0, self.cfg.jitter) if self.cfg.jitter > 0 else 0.0
        arrival = departed + self.cfg.delay + jitter
        arrival = max(arrival, self._last_arrival[is_ack])  # keep the link FIFO
        self._last_arrival[is_ack] = arrival

        self.scheduler.schedule(arrival - now, deliver, packet)
        return departed
