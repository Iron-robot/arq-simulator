"""ARQ Protocol Simulator.

A discrete-event simulator for three Automatic Repeat reQuest (ARQ) protocols:
Stop-and-Wait, Go-Back-N and Selective Repeat, running over an unreliable
channel that can lose, corrupt and delay packets.
"""

from arq.config import ChannelConfig, SimConfig
from arq.metrics import RunResult
from arq.protocols import PROTOCOLS, GoBackN, SelectiveRepeat, StopAndWait, get_protocol, run_protocol

__all__ = [
    "ChannelConfig",
    "SimConfig",
    "RunResult",
    "PROTOCOLS",
    "StopAndWait",
    "GoBackN",
    "SelectiveRepeat",
    "get_protocol",
    "run_protocol",
]

__version__ = "1.0.0"
