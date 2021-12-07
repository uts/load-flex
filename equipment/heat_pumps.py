from dataclasses import dataclass
from datetime import timedelta

from equipment.equipment import Equipment, ThermalDispatch


@dataclass
class HeatPump(Equipment):
    """ One way heat pump. Can represent either heating or cooling]

    Discharge is a representation of thermal energy supplied to a site
    """
    thermal_capacity: float
    cop: float

    @property
    def input_capacity(self):
        return self.thermal_capacity / self.cop

    @property
    def output_capacity(self):
        return self.thermal_capacity

    def dispatch_request(
            self,
            proposal: ThermalDispatch,
            sample_rate: timedelta
    ) -> ThermalDispatch:
        time_step_hours = sample_rate / timedelta(hours=1)
        max_dispatch = self.thermal_capacity * time_step_hours
        return ThermalDispatch(
            charge=0.0,
            discharge=min(max_dispatch, proposal.discharge),
            coefficient_of_performance=self.cop
        )

    def max_dispatch(
            self,
            sample_rate: timedelta
    ) -> ThermalDispatch:
        time_step_hours = sample_rate / timedelta(hours=1)
        max_dispatch = self.thermal_capacity * time_step_hours
        return ThermalDispatch(
            charge=0.0,
            discharge=max_dispatch,
            coefficient_of_performance=self.cop
        )