"""Correctness tests for all three ARQ protocols.

The core guarantee of any ARQ protocol: no matter what the channel does
(lose, corrupt, delay), the receiver hands the application every packet
exactly once and in the original order.
"""

import pytest

from arq import ChannelConfig, SimConfig, run_protocol
from arq.protocols import GoBackN, SelectiveRepeat, StopAndWait, get_protocol, make_payload

ALL = ["sw", "gbn", "sr"]

CHANNELS = {
    "perfect": ChannelConfig(),
    "data_loss": ChannelConfig(loss_rate=0.2),
    "ack_loss": ChannelConfig(ack_loss_rate=0.3),
    "corruption": ChannelConfig(corrupt_rate=0.2),
    "jitter": ChannelConfig(delay=10, jitter=15),
    "everything": ChannelConfig(loss_rate=0.2, ack_loss_rate=0.2, corrupt_rate=0.1, delay=5, jitter=10),
    "brutal": ChannelConfig(loss_rate=0.5, ack_loss_rate=0.5, corrupt_rate=0.1),
}


def expected(n):
    return [make_payload(i) for i in range(n)]


def run(key, n=200, window=4, seed=0, **kwargs):
    channel = kwargs.pop("channel", ChannelConfig())
    cfg = SimConfig(num_packets=n, window_size=window, seed=seed, channel=channel, **kwargs)
    proto = get_protocol(key)(cfg)
    return proto, proto.run()


@pytest.mark.parametrize("key", ALL)
@pytest.mark.parametrize("channel_name", list(CHANNELS))
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_all_packets_delivered_in_order_without_duplicates(key, channel_name, seed):
    proto, result = run(key, n=150, window=5, seed=seed, channel=CHANNELS[channel_name])
    assert result.completed
    assert proto.delivered == expected(150)          # in order, nothing missing
    assert len(set(proto.delivered)) == len(proto.delivered)  # no duplicates delivered
    assert result.delivered == 150


@pytest.mark.parametrize("key", ALL)
def test_perfect_channel_needs_no_retransmissions(key):
    _, result = run(key, n=300, channel=ChannelConfig())
    assert result.retransmissions == 0
    assert result.counters.timeouts == 0
    assert result.total_packets_sent == 300
    assert result.efficiency == 1.0


@pytest.mark.parametrize("key", ALL)
def test_packet_accounting_adds_up(key):
    _, result = run(key, n=300, channel=CHANNELS["everything"])
    c = result.counters
    assert c.data_sent == 300 + c.retransmissions
    assert c.retransmissions > 0
    assert 0 < result.efficiency < 1


def test_stop_and_wait_timing_matches_formula():
    # Each packet costs exactly one round trip: tx_time + delay (data) + delay (ACK).
    _, result = run("sw", n=50, channel=ChannelConfig(delay=10), tx_time=1.0)
    assert result.total_time_ms == pytest.approx(50 * (1.0 + 2 * 10))


def test_stop_and_wait_ignores_window_setting():
    proto, _ = run("sw", window=16)
    assert proto.window == 1
    assert proto.seq_mod == 2


@pytest.mark.parametrize("key", ["gbn", "sr"])
def test_window_of_one_behaves_like_stop_and_wait(key):
    _, sw = run("sw", n=100)
    _, other = run(key, n=100, window=1)
    assert other.total_time_ms == pytest.approx(sw.total_time_ms)


@pytest.mark.parametrize("key", ["gbn", "sr"])
def test_bigger_window_is_faster_on_clean_channel(key):
    _, small = run(key, n=400, window=1)
    _, big = run(key, n=400, window=8)
    assert big.throughput_pps > 3 * small.throughput_pps


def test_selective_repeat_retransmits_less_than_go_back_n():
    channel = ChannelConfig(loss_rate=0.2, ack_loss_rate=0.2)
    gbn_retx = sum(run("gbn", n=500, window=8, seed=s, channel=channel)[1].retransmissions for s in range(3))
    sr_retx = sum(run("sr", n=500, window=8, seed=s, channel=channel)[1].retransmissions for s in range(3))
    assert sr_retx < gbn_retx


# ---- sequence-number wrap-around: the tightest legal settings -------------

@pytest.mark.parametrize("seed", range(5))
def test_go_back_n_with_smallest_legal_sequence_space(seed):
    # 3 bits -> seq numbers 0..7, window 7 is the largest GBN allows.
    proto, result = run("gbn", n=300, window=7, seq_bits=3, seed=seed, channel=CHANNELS["everything"])
    assert result.completed and proto.delivered == expected(300)


@pytest.mark.parametrize("seed", range(5))
def test_selective_repeat_with_smallest_legal_sequence_space(seed):
    # 3 bits -> seq numbers 0..7, window 4 is the largest SR allows.
    proto, result = run("sr", n=300, window=4, seq_bits=3, seed=seed, channel=CHANNELS["everything"])
    assert result.completed and proto.delivered == expected(300)


@pytest.mark.parametrize("key", ALL)
def test_premature_timeouts_still_correct(key):
    """A timeout far shorter than the round trip causes many needless
    retransmissions, but must never break delivery."""
    proto, result = run(key, n=60, window=4, timeout=2.0, channel=CHANNELS["everything"])
    assert result.completed and proto.delivered == expected(60)
    assert result.retransmissions > 60


def test_go_back_n_rejects_window_too_large_for_sequence_space():
    with pytest.raises(ValueError, match="Go-Back-N"):
        GoBackN(SimConfig(window_size=8, seq_bits=3))


def test_selective_repeat_rejects_window_too_large_for_sequence_space():
    with pytest.raises(ValueError, match="Selective Repeat"):
        SelectiveRepeat(SimConfig(window_size=5, seq_bits=3))


@pytest.mark.parametrize("window, gbn_bits, sr_bits", [(1, 3, 3), (7, 3, 4), (8, 4, 4), (16, 5, 5), (17, 5, 6)])
def test_default_sequence_bits_are_safe(window, gbn_bits, sr_bits):
    assert GoBackN(SimConfig(window_size=window)).seq_bits == gbn_bits
    assert SelectiveRepeat(SimConfig(window_size=window)).seq_bits == sr_bits


# ---- reproducibility & settings ------------------------------------------

@pytest.mark.parametrize("key", ALL)
def test_same_seed_gives_identical_results(key):
    _, a = run(key, seed=42, channel=CHANNELS["everything"])
    _, b = run(key, seed=42, channel=CHANNELS["everything"])
    assert a.to_dict() == b.to_dict()


@pytest.mark.parametrize("bad", [
    {"num_packets": 0},
    {"window_size": 0},
    {"timeout": -1},
    {"channel": ChannelConfig(loss_rate=1.0)},
    {"channel": ChannelConfig(corrupt_rate=-0.1)},
    {"channel": ChannelConfig(delay=-5)},
])
def test_invalid_settings_rejected(bad):
    with pytest.raises(ValueError):
        StopAndWait(SimConfig(**bad))


def test_unknown_protocol_name():
    with pytest.raises(ValueError, match="unknown protocol"):
        run_protocol("tcp", SimConfig())


def test_run_stops_at_max_time():
    _, result = run("sw", n=1000, max_time=500.0)
    assert not result.completed
    assert result.delivered < 1000
