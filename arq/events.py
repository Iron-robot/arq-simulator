"""A tiny discrete-event scheduler.

Instead of real threads and `time.sleep`, the simulator keeps a priority queue
of future events ordered by simulated time. Running the simulation means:
pop the earliest event, jump the clock to its time, run its callback (which
may schedule more events), repeat. This makes runs fast and, with a fixed
random seed, perfectly repeatable.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, List, Tuple


@dataclass(order=True)
class Event:
    time: float
    order: int                                        # tie-breaker: FIFO for equal times
    callback: Callable[..., None] = field(compare=False)
    args: Tuple[Any, ...] = field(compare=False, default=())
    cancelled: bool = field(compare=False, default=False)

    def cancel(self) -> None:
        """Cancelling is lazy: the event stays in the heap but is skipped."""
        self.cancelled = True


class EventScheduler:
    def __init__(self) -> None:
        self.now: float = 0.0
        self._queue: List[Event] = []
        self._counter = itertools.count()
        self.events_processed = 0

    def schedule(self, delay: float, callback: Callable[..., None], *args: Any) -> Event:
        if delay < 0:
            raise ValueError("cannot schedule an event in the past")
        event = Event(self.now + delay, next(self._counter), callback, args)
        heapq.heappush(self._queue, event)
        return event

    def run(self, stop_when: Callable[[], bool], max_time: float) -> bool:
        """Process events until `stop_when()` is true.

        Returns True if the stop condition was met, False if the queue ran dry
        or the clock passed `max_time` first.
        """
        while self._queue:
            if stop_when():
                return True
            event = heapq.heappop(self._queue)
            if event.cancelled:
                continue
            if event.time > max_time:
                return False
            self.now = event.time
            self.events_processed += 1
            event.callback(*event.args)
        return stop_when()
