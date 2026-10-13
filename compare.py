#!/usr/bin/env python3
"""Run all three protocols across a range of loss rates and save charts.

    python compare.py                       # defaults: 500 packets, window 8, 5 seeds
    python compare.py --packets 1000 --window 16 --seeds 10

Outputs (in ./results by default):
    results.csv                     every averaged data point
    throughput_vs_loss.png
    retransmissions_vs_loss.png
    efficiency_vs_loss.png
    window_size_vs_throughput.png
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")  # render to files; no display needed
import matplotlib.pyplot as plt  # noqa: E402

from arq import ChannelConfig, SimConfig, run_protocol  # noqa: E402
from arq.protocols import PROTOCOLS  # noqa: E402

LOSS_RATES = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]
WINDOW_SIZES = [1, 2, 4, 8, 16, 32]

# One fixed colour per protocol (colour follows the protocol in every chart).
COLORS = {"sw": "#2a78d6", "gbn": "#eb6834", "sr": "#1baf7a"}
MARKERS = {"sw": "o", "gbn": "s", "sr": "^"}
# Stop-and-Wait is dashed and drawn on top: it often overlaps Selective Repeat exactly.
LINESTYLES = {"sw": (0, (4, 2)), "gbn": "-", "sr": "-"}
ZORDER = {"sw": 4, "gbn": 3, "sr": 2}
TEXT, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def average_run(key: str, packets: int, window: int, loss: float, corrupt: float,
                delay: float, seeds: int) -> Dict[str, float]:
    runs = []
    for seed in range(seeds):
        cfg = SimConfig(
            num_packets=packets, window_size=window, seed=seed,
            channel=ChannelConfig(loss_rate=loss, ack_loss_rate=loss,
                                  corrupt_rate=corrupt, delay=delay),
        )
        result = run_protocol(key, cfg)
        if not result.completed or result.delivered != packets:
            raise RuntimeError(f"{key} did not complete at loss={loss}, seed={seed}")
        runs.append(result)
    mean = statistics.mean
    return {
        "throughput_kbps": mean(r.throughput_kbps for r in runs),
        "throughput_pps": mean(r.throughput_pps for r in runs),
        "packets_sent": mean(r.total_packets_sent for r in runs),
        "retransmissions": mean(r.retransmissions for r in runs),
        "efficiency": mean(r.efficiency for r in runs),
        "utilization": mean(r.utilization for r in runs),
        "time_ms": mean(r.total_time_ms for r in runs),
    }


def style_axes(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=13, color=TEXT, pad=12, fontweight="bold")
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED)


def line_chart(path: Path, x: List[float], series: Dict[str, List[float]], title: str,
               xlabel: str, ylabel: str, percent_x: bool = False, percent_y: bool = False,
               log_y: bool = False, log2_x: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    for key, ys in series.items():
        ax.plot(x, ys, color=COLORS[key], marker=MARKERS[key], markersize=6,
                linewidth=2, linestyle=LINESTYLES[key], zorder=ZORDER[key],
                label=PROTOCOLS[key].name)
    style_axes(ax, title, xlabel, ylabel)

    # Axes: ticks only where we actually measured.
    if log2_x:
        ax.set_xscale("log", base=2)
    ax.set_xticks(x)
    if percent_x:
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    else:
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    if percent_y:
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        ax.set_ylim(0, 1.05)
    elif log_y:
        ax.set_yscale("symlog", linthresh=10)
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    else:
        ax.set_ylim(bottom=0)
    ax.set_xlim(x[0], x[-1])
    ax.margins(x=0)
    fig.subplots_adjust(left=0.1, right=0.74, top=0.88, bottom=0.2)

    # Direct labels at the right end of each line, pushed apart so they never overlap.
    # Text stays in ink colour; the marker beside the line carries identity.
    to_px = ax.transData.transform
    ends = sorted(((to_px((x[-1], ys[-1]))[1], key, ys[-1]) for key, ys in series.items()))
    min_gap_px = 13 * fig.dpi / 72
    placed: List[float] = []
    for y_px, _, _ in ends:
        placed.append(max(y_px, placed[-1] + min_gap_px) if placed else y_px)
    top_px = ax.bbox.y1                       # keep labels below the top of the plot
    for i in range(len(placed) - 1, -1, -1):
        ceiling = top_px if i == len(placed) - 1 else placed[i + 1] - min_gap_px
        placed[i] = min(placed[i], ceiling)
    for (y_px, key, value), y_new in zip(ends, placed):
        label = f"{value:.0%}" if percent_y else f"{value:,.0f}"
        ax.annotate(f"{PROTOCOLS[key].name}: {label}", (x[-1], value),
                    xytext=(10, (y_new - y_px) * 72 / fig.dpi), textcoords="offset points",
                    va="center", fontsize=8.5, color=TEXT, annotation_clip=False)

    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.12), ncol=3, fontsize=9)
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--packets", type=int, default=500)
    p.add_argument("--window", type=int, default=8)
    p.add_argument("--seeds", type=int, default=5, help="runs averaged per data point")
    p.add_argument("--corrupt", type=float, default=0.0)
    p.add_argument("--delay", type=float, default=10.0)
    p.add_argument("--out", default="results")
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    print(f"Loss sweep: {args.packets} packets, window {args.window}, "
          f"{args.seeds} seeds per point, loss applied to data AND ACKs\n")
    print(f"{'protocol':<18}{'loss':>6}{'kbps':>10}{'sent':>9}{'retx':>9}{'effic.':>9}{'util.':>8}")
    loss_data: Dict[str, Dict[str, List[float]]] = {k: {} for k in PROTOCOLS}
    for key in PROTOCOLS:
        for loss in LOSS_RATES:
            m = average_run(key, args.packets, args.window, loss, args.corrupt, args.delay, args.seeds)
            for metric, value in m.items():
                loss_data[key].setdefault(metric, []).append(value)
            rows.append({"experiment": "loss_sweep", "protocol": key, "loss": loss,
                         "window": 1 if key == "sw" else args.window, **m})
            print(f"{PROTOCOLS[key].name:<18}{loss:>6.0%}{m['throughput_kbps']:>10.1f}"
                  f"{m['packets_sent']:>9.0f}{m['retransmissions']:>9.0f}"
                  f"{m['efficiency']:>9.1%}{m['utilization']:>8.1%}")

    sweep_loss = 0.10
    print(f"\nWindow sweep at {sweep_loss:.0%} loss")
    window_data: Dict[str, List[float]] = {k: [] for k in PROTOCOLS}
    for key in PROTOCOLS:
        for w in WINDOW_SIZES:
            m = average_run(key, args.packets, w, sweep_loss, args.corrupt, args.delay, args.seeds)
            window_data[key].append(m["throughput_kbps"])
            rows.append({"experiment": "window_sweep", "protocol": key, "loss": sweep_loss,
                         "window": 1 if key == "sw" else w, **m})
        print(f"  {PROTOCOLS[key].name:<18}" + "  ".join(
            f"w={w}: {v:,.0f}" for w, v in zip(WINDOW_SIZES, window_data[key])))

    with open(out / "results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    subtitle = f"{args.packets} packets, window {args.window}, avg of {args.seeds} runs"
    line_chart(out / "throughput_vs_loss.png", LOSS_RATES,
               {k: v["throughput_kbps"] for k, v in loss_data.items()},
               f"Throughput vs loss rate  ({subtitle})", "Loss rate (data and ACKs)", "Throughput (kbps)",
               percent_x=True)
    line_chart(out / "retransmissions_vs_loss.png", LOSS_RATES,
               {k: v["retransmissions"] for k, v in loss_data.items()},
               f"Retransmissions vs loss rate  ({subtitle})", "Loss rate (data and ACKs)",
               "Retransmissions (log scale)", percent_x=True, log_y=True)
    line_chart(out / "efficiency_vs_loss.png", LOSS_RATES,
               {k: v["efficiency"] for k, v in loss_data.items()},
               f"Efficiency vs loss rate  ({subtitle})", "Loss rate (data and ACKs)",
               "Efficiency (unique packets / packets sent)", percent_x=True, percent_y=True)
    line_chart(out / "window_size_vs_throughput.png", WINDOW_SIZES, window_data,
               f"Throughput vs window size at {sweep_loss:.0%} loss  ({args.packets} packets)",
               "Window size (packets, log scale)", "Throughput (kbps)", log2_x=True)

    print(f"\nSaved results.csv and 4 charts to {out.resolve()}")


if __name__ == "__main__":
    main()
