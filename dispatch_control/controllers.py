from dataclasses import dataclass

from datetime import datetime
from typing import List

from dispatch_control.dispatch_schedulers import DispatchSchedule
from dispatch_control.setpoints import SetPoints, SetPointProposal
from time_tools.schedulers import Period


@dataclass
class ParamController:
    setpoints: SetPoints = None
    dispatch_schedule: DispatchSchedule = None

    @property
    def reportables(self):
        setpoint_report = {
            'charge_setpoint': self.setpoints.charge_setpoint,
            'discharge_setpoint': self.setpoints.discharge_setpoint,
            'universal_setpoint': self.setpoints.universal_setpoint,
        } if self.setpoints else {}
        return setpoint_report

    def set_setpoints(self, setpoint_proposal: SetPointProposal, dt: datetime):
        self.setpoints.set_setpoints(setpoint_proposal, dt)

    def append_dispatch_schedule(
            self,
            charge_periods: List[Period],
            discharge_periods: List[Period]
    ):
        self.dispatch_schedule.append_schedule(
            charge_periods,
            discharge_periods
        )

