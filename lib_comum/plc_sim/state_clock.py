"""Shared synthetic-time clock for PLC emulators.

PT: Mapeia a hora actual de relógio para um instante simulado no dataset
da fábrica. Permite que vários emuladores (Modbus, OPC-UA) e o simulador
MQTT contem a mesma história, no mesmo tempo lógico.
EN: Maps wall-clock time to a simulated instant inside the factory
dataset. Lets multiple emulators (Modbus, OPC-UA) and the MQTT simulator
share the same logical timeline.

The clock is anchored at construction time::

    clock = SimClock(sim_start=dataset_first_ts, speed_up=600.0)
    sim_ts = clock.now_sim()  # → simulated UTC datetime
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass(slots=True)
class SimClock:
    """Map wall-clock time to a simulated UTC instant.

    PT: Relógio que comprime tempo real em tempo simulado.
    EN: Clock that compresses wall time into simulated time.

    Attributes:
        sim_start: simulated UTC instant the clock starts at.
        speed_up: wall-clock seconds → simulated seconds factor.
        wall_start: monotonic timestamp at which the clock was constructed
            (defaults to ``time.monotonic()`` at instantiation).
    """

    sim_start: datetime
    speed_up: float = 1.0
    wall_start: float = field(default_factory=time.monotonic)

    def now_sim(self) -> datetime:
        """Return the current simulated UTC instant.

        PT: Devolve o instante simulado actual.
        EN: Returns the current simulated UTC instant.
        """
        elapsed_wall = time.monotonic() - self.wall_start
        elapsed_sim = elapsed_wall * self.speed_up
        if self.sim_start.tzinfo is None:
            anchor = self.sim_start.replace(tzinfo=UTC)
        else:
            anchor = self.sim_start
        return anchor + timedelta(seconds=elapsed_sim)
