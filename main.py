#!/usr/bin/env python3
"""Command-line interface for the ARQ Protocol Simulator.

Examples
--------
    python main.py --protocol gbn --packets 1000 --loss 0.1 --window 4
    python main.py --protocol sr  --packets 500 --loss 0.2 --corrupt 0.05 --jitter 5
    python main.py --protocol all --packets 1000 --loss 0.1 --window 8
    python main.py --protocol sw  --packets 5 --loss 0.3 --seed 7 --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from arq import ChannelConfig, SimConfig, run_protocol
from arq.protocols import PROTOCOLS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Simulate Stop-and-Wait, Go-Back-N and Selective Repeat ARQ over a lossy channel.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--protocol", "-p", default="gbn", choices=[*PROTOCOLS, "all"],
                   help="sw = Stop-and-Wait, gbn = Go-Back-N, sr = Selective Repeat, all = run all three")
    p.add_argument("--packets", "-n", type=int, default=1000, help="number of data packets to deliver")
    p.add_argument("--window", "-w", type=int, default=4, help="sender window size (ignored by sw)")
    p.add_argument("--seq-bits", type=int, default=None,
                   help="bits in the sequence-number field (default: smallest safe value)")

    ch = p.add_argument_group("channel errors")
    ch.add_argument("--loss", type=float, default=0.0, help="probability a data packet is lost")
    ch.add_argument("--ack-loss", type=float, default=None,
                    help="probability an ACK is lost (default: same as --loss)")
    ch.add_argument("--corrupt", type=float, default=0.0,
                    help="probability a packet has a bit flipped (caught by the checksum)")
    ch.add_argument("--delay", type=float, default=10.0, help="one-way propagation delay (ms)")
    ch.add_argument("--jitter", type=float, default=0.0, help="extra random delay, 0..jitter ms")

    t = p.add_argument_group("timing")
    t.add_argument("--timeout", type=float, default=None,
                   help="retransmission timeout in ms (default: derived from delay, jitter, window)")
    t.add_argument("--tx-time", type=float, default=1.0, help="ms to transmit one data packet")
    t.add_argument("--packet-size", type=int, default=1000, help="bytes per data packet")

    o = p.add_argument_group("output")
    o.add_argument("--seed", type=int, default=None, help="random seed for a repeatable run")
    o.add_argument("--verbose", "-v", action="store_true", help="print every send/receive/timeout event")
    o.add_argument("--json", action="store_true", help="print results as JSON")
    return p


def config_from_args(args: argparse.Namespace) -> SimConfig:
    return SimConfig(
        num_packets=args.packets,
        window_size=args.window,
        seq_bits=args.seq_bits,
        timeout=args.timeout,
        tx_time=args.tx_time,
        packet_size=args.packet_size,
        seed=args.seed,
        verbose=args.verbose,
        channel=ChannelConfig(
            loss_rate=args.loss,
            ack_loss_rate=args.loss if args.ack_loss is None else args.ack_loss,
            corrupt_rate=args.corrupt,
            delay=args.delay,
            jitter=args.jitter,
        ),
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    keys = list(PROTOCOLS) if args.protocol == "all" else [args.protocol]

    results = []
    for key in keys:
        try:
            results.append(run_protocol(key, config_from_args(args)))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        c = config_from_args(args).channel
        print(f"Channel: loss={c.loss_rate:.0%}  ack-loss={c.ack_loss_rate:.0%}  "
              f"corrupt={c.corrupt_rate:.0%}  delay={c.delay} ms  jitter={c.jitter} ms")
        for r in results:
            print()
            print(r.summary())

    return 0 if all(r.completed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
