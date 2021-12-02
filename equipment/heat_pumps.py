from dataclasses import dataclass
from datetime import timedelta

from equipment.equipment import Equipment, ThermalDispatch


@dataclass
class HeatPump(Equipment):
    """ One way heat pump. Can represent either heating or cooling
    """
    thermal_capacity: float
    cop: float

    @property
    def input_capacity(self):
        return self.thermal_capacity

    @property
    def output_capacity(self):
        return 0.0

    def dispatch_request(
            self,
            proposal: ThermalDispatch,
            sample_rate: timedelta
    ) -> ThermalDispatch:
        time_step_hours = sample_rate / timedelta(hours=1)
        max_dispatch = self.thermal_capacity * time_step_hours
        return ThermalDispatch(
            charge=min(max_dispatch, proposal.charge),
            discharge=0.0,
            coefficient_of_performance=self.cop
        )
