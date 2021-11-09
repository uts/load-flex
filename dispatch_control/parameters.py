from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from time_tools.schedulers import EventSchedule, PeriodSchedule


@dataclass
class ParamSetterSchedule:
    """
    """
    charge_params: EventSchedule = None
    discharge_params: EventSchedule = None
    universal_params: EventSchedule = None
    control_params_pauses: PeriodSchedule = None

    def __post_init__(self):
        if not self.universal_params:
            self.universal_params = EventSchedule([])
        if not self.charge_params:
            self.charge_params = EventSchedule([])
        if not self.discharge_params:
            self.discharge_params = EventSchedule([])
        if not self.control_params_pauses:
            self.control_params_pauses = PeriodSchedule([])

    def params_pause_due(self, dt: datetime) -> bool:
        return self.control_params_pauses.period_active(dt)

    def universal_params_due(self, dt: datetime) -> bool:
        return False if self.params_pause_due(dt) else self.universal_params.event_due(dt)

    def charge_params_due(self, dt: datetime) -> bool:
        return False if self.params_pause_due(dt) else self.charge_params.event_due(dt)

    def discharge_params_due(self, dt: datetime) -> bool:
        return False if self.params_pause_due(dt) else self.discharge_params.event_due(dt)

    def any_event_due(self, dt: datetime) -> bool:
        return self.charge_params_due(dt) \
               or self.discharge_params_due(dt) \
               or self.universal_params_due(dt)