"""Performance measurement for one run."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Counters:
    """Raw counts, updated live by the channel and protocols."""

    data_sent: int = 0           # every data transmission, originals + retransmissions
    retransmissions: int = 0     # data transmissions of a packet that was already sent once
    acks_sent: int = 0
    data_lost: int = 0
    acks_lost: int = 0
    data_corrupted: int = 0
    acks_corrupted: int = 0
    timeouts: int = 0
    duplicates_discarded: int = 0  # valid data packets the receiver did not deliver (dups / out of window)
    out_of_order_buffered: int = 0  # SR only: packets held until the gap before them is filled


@dataclass
class RunResult:
    protocol: str
    num_packets: int
    window_size: int
    seq_bits: int
    timeout: float
    delivered: int
    completed: bool
    total_time_ms: float
    packet_size: int
    tx_time: float
    counters: Counters = field(default_factory=Counters)

    # ---- derived metrics -------------------------------------------------

    @property
    def total_packets_sent(self) -> int:
        """Data transmissions only (what the question 'how many packets did we send' usually means)."""
        return self.counters.data_sent

    @property
    def retransmissions(self) -> int:
        return self.counters.retransmissions

    @property
    def throughput_pps(self) -> float:
        """Useful (delivered) packets per second of simulated time."""
        if self.total_time_ms <= 0:
            return 0.0
        return self.delivered / (self.total_time_ms / 1000.0)

    @property
    def throughput_kbps(self) -> float:
        """Goodput: useful bits per second, in kilobits."""
        return self.throughput_pps * self.packet_size * 8 / 1000.0

    @property
    def efficiency(self) -> float:
        """Share of transmissions that were not wasted: unique packets / packets sent.

        1.0 means nothing was ever sent twice.
        """
        if self.counters.data_sent == 0:
            return 0.0
        return self.delivered / self.counters.data_sent

    @property
    def utilization(self) -> float:
        """Share of time the link spent carrying *useful* data.

        This is the classic textbook 'sender utilization':
        (time to transmit the unique packets) / (total time).
        """
        if self.total_time_ms <= 0:
            return 0.0
        return (self.delivered * self.tx_time) / self.total_time_ms

    # ---- output helpers --------------------------------------------------

    def to_dict(self) -> dict:
        data = {k: v for k, v in asdict(self).items() if k != "counters"}
        data.update(asdict(self.counters))
        data.update(
            total_packets_sent=self.total_packets_sent,
            throughput_pps=round(self.throughput_pps, 3),
            throughput_kbps=round(self.throughput_kbps, 3),
            efficiency=round(self.efficiency, 4),
            utilization=round(self.utilization, 4),
        )
        return data

    def summary(self) -> str:
        c = self.counters
        status = "COMPLETED" if self.completed else "DID NOT FINISH (hit max_time)"
        rows = [
            ("Protocol", self.protocol),
            ("Status", status),
            ("Window size / seq bits", f"{self.window_size} / {self.seq_bits} (seq numbers 0..{2 ** self.seq_bits - 1})"),
            ("Timeout", f"{self.timeout:.2f} ms"),
            ("Packets delivered", f"{self.delivered} / {self.num_packets}"),
            ("Total data packets sent", f"{c.data_sent}"),
            ("Retransmissions", f"{c.retransmissions}"),
            ("Timeouts", f"{c.timeouts}"),
            ("ACKs sent", f"{c.acks_sent}"),
            ("Lost (data / ACK)", f"{c.data_lost} / {c.acks_lost}"),
            ("Corrupted (data / ACK)", f"{c.data_corrupted} / {c.acks_corrupted}"),
            ("Duplicates discarded", f"{c.duplicates_discarded}"),
            ("Simulated time", f"{self.total_time_ms:,.1f} ms"),
            ("Throughput", f"{self.throughput_pps:,.1f} packets/s  ({self.throughput_kbps:,.1f} kbps)"),
            ("Efficiency", f"{self.efficiency:.1%}  (unique packets / packets sent)"),
            ("Link utilization", f"{self.utilization:.1%}  (useful transmit time / total time)"),
        ]
        width = max(len(label) for label, _ in rows)
        line = "-" * (width + 50)
        body = "\n".join(f"{label:<{width}} : {value}" for label, value in rows)
        return f"{line}\n{body}\n{line}"
