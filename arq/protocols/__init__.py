from typing import Dict, Type

from arq.config import SimConfig
from arq.metrics import RunResult
from arq.protocols.base import ARQProtocol, make_payload
from arq.protocols.go_back_n import GoBackN
from arq.protocols.selective_repeat import SelectiveRepeat
from arq.protocols.stop_and_wait import StopAndWait

PROTOCOLS: Dict[str, Type[ARQProtocol]] = {
    StopAndWait.key: StopAndWait,
    GoBackN.key: GoBackN,
    SelectiveRepeat.key: SelectiveRepeat,
}


def get_protocol(key: str) -> Type[ARQProtocol]:
    try:
        return PROTOCOLS[key.lower()]
    except KeyError:
        raise ValueError(f"unknown protocol {key!r}; choose from {', '.join(PROTOCOLS)}") from None


def run_protocol(key: str, config: SimConfig) -> RunResult:
    return get_protocol(key)(config).run()


__all__ = ["ARQProtocol", "StopAndWait", "GoBackN", "SelectiveRepeat",
           "PROTOCOLS", "get_protocol", "run_protocol", "make_payload"]
