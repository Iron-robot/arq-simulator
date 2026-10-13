"""Settings for a simulation run.

All times are in milliseconds of *simulated* time. The simulator never sleeps,
so a run that represents minutes of network time finishes in a fraction of a
second of real time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChannelConfig:
    """How unreliable the fake network is."""

    loss_rate: float = 0.0       # chance a DATA packet disappears
    ack_loss_rate: float = 0.0   # chance an ACK disappears
    corrupt_rate: float = 0.0    # chance a packet (data or ACK) gets a flipped bit
    delay: float = 10.0          # one-way propagation delay in ms
    jitter: float = 0.0          # extra random delay, uniform in [0, jitter] ms

    def validate(self) -> None:
        for name in ("loss_rate", "ack_loss_rate", "corrupt_rate"):
            value = getattr(self, name)
            if not 0.0 <= value < 1.0:
                # A rate of 1.0 means nothing ever gets through: the run could never finish.
                raise ValueError(f"{name} must be in [0, 1), got {value}")
        if self.delay < 0:
            raise ValueError(f"delay must be >= 0, got {self.delay}")
        if self.jitter < 0:
            raise ValueError(f"jitter must be >= 0, got {self.jitter}")


@dataclass
class SimConfig:
    """Everything needed to describe one simulation run."""

    num_packets: int = 100
    window_size: int = 4
    seq_bits: Optional[int] = None    # None = smallest safe value for the protocol
    timeout: Optional[float] = None   # None = derived from delay, jitter and window
    tx_time: float = 1.0              # ms to push one data packet onto the link
    packet_size: int = 1000           # bytes per data packet (for throughput in kbps)
    seed: Optional[int] = None        # set it to make a run exactly repeatable
    max_time: float = 1e9             # safety stop for the simulated clock (ms)
    verbose: bool = False             # print an event-by-event trace
    channel: ChannelConfig = field(default_factory=ChannelConfig)

    def validate(self) -> None:
        if self.num_packets < 1:
            raise ValueError("num_packets must be >= 1")
        if self.window_size < 1:
            raise ValueError("window_size must be >= 1")
        if self.seq_bits is not None and self.seq_bits < 1:
            raise ValueError("seq_bits must be >= 1")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be > 0")
        if self.tx_time <= 0:
            raise ValueError("tx_time must be > 0")
        if self.packet_size < 1:
            raise ValueError("packet_size must be >= 1")
        self.channel.validate()
