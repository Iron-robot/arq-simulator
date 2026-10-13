"""Tests for packets, checksums, the event scheduler and the lossy channel."""

import random

import pytest

from arq.channel import Channel
from arq.config import ChannelConfig
from arq.events import EventScheduler
from arq.metrics import Counters
from arq.packet import Packet


# ---- packets & checksums ---------------------------------------------------

def test_fresh_packets_have_valid_checksums():
    assert Packet.data(5, b"hello").is_valid()
    assert Packet.ack(5).is_valid()


def test_every_corruption_is_detected():
    rng = random.Random(0)
    for i in range(5000):
        pkt = Packet.ack(i % 64) if i % 2 else Packet.data(i % 64, f"payload-{i}".encode())
        bad = pkt.corrupted(rng)
        assert bad != pkt
        assert not bad.is_valid()


def test_checksum_covers_the_ack_flag():
    data = Packet.data(3, b"")
    forged_ack = Packet(seq=3, payload=b"", is_ack=True, checksum=data.checksum)
    assert not forged_ack.is_valid()


# ---- scheduler ------------------------------------------------------------

def test_scheduler_runs_events_in_time_order_and_skips_cancelled():
    s = EventScheduler()
    seen = []
    s.schedule(5, seen.append, "b")
    s.schedule(1, seen.append, "a")
    s.schedule(5, seen.append, "c")      # same time as "b": runs after it (FIFO)
    s.schedule(3, seen.append, "x").cancel()
    s.run(stop_when=lambda: False, max_time=100)
    assert seen == ["a", "b", "c"]
    assert s.now == 5


# ---- channel --------------------------------------------------------------

def make_channel(**cfg):
    sched = EventScheduler()
    counters = Counters()
    ch = Channel(ChannelConfig(**cfg), sched, random.Random(1), counters, tx_time=1.0)
    return ch, sched, counters


def send_many(n, is_ack=False, **cfg):
    ch, sched, counters = make_channel(**cfg)
    arrived = []
    for i in range(n):
        pkt = Packet.ack(i) if is_ack else Packet.data(i, b"x")
        ch.send(pkt, arrived.append)
    sched.run(stop_when=lambda: False, max_time=float("inf"))
    return arrived, counters, sched


def test_perfect_channel_delivers_everything():
    arrived, counters, _ = send_many(1000)
    assert len(arrived) == 1000
    assert all(p.is_valid() for p in arrived)
    assert counters.data_lost == 0


@pytest.mark.parametrize("rate", [0.1, 0.3, 0.6])
def test_loss_rate_is_respected(rate):
    arrived, counters, _ = send_many(20_000, loss_rate=rate)
    observed = counters.data_lost / 20_000
    assert observed == pytest.approx(rate, abs=0.015)
    assert len(arrived) + counters.data_lost == 20_000


def test_ack_loss_uses_its_own_rate():
    arrived, counters, _ = send_many(5000, is_ack=True, loss_rate=0.9, ack_loss_rate=0.0)
    assert len(arrived) == 5000
    arrived, counters, _ = send_many(5000, is_ack=True, loss_rate=0.0, ack_loss_rate=0.5)
    assert counters.acks_lost / 5000 == pytest.approx(0.5, abs=0.03)


def test_corrupted_packets_arrive_but_fail_checksum():
    arrived, counters, _ = send_many(10_000, corrupt_rate=0.25)
    invalid = sum(not p.is_valid() for p in arrived)
    assert invalid == counters.data_corrupted
    assert invalid / 10_000 == pytest.approx(0.25, abs=0.02)


def test_delay_and_transmission_time():
    # 10 data packets back-to-back: the last one leaves at t=10 and arrives at t=10+delay.
    _, _, sched = send_many(10, delay=7)
    assert sched.now == pytest.approx(10 + 7)


def test_jitter_adds_delay_but_never_reorders():
    arrived, _, _ = send_many(2000, delay=5, jitter=50)
    seqs = [p.seq for p in arrived]
    assert seqs == sorted(seqs)
