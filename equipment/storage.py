from dataclasses import dataclass, field
from datetime import timedelta
from typing import Tuple

from equipment.equipment import Storage, Dispatch
from equipment.state_models import StateBasedProperty

REPORT_ON = (
    'state_of_charge',
    'available_energy',
    'available_storage',
    'cycle_count'
    )

BATTERY_REPORT_ON = (
    *REPORT_ON,
)

THERMAL_REPORT_ON = (
    'discharge_capacity',
    'charge_capacity',
    'charging_cop',
    *REPORT_ON
)


@dataclass
class Battery(Storage):
    report_on: Tuple[str] = field(default=BATTERY_REPORT_ON, init=False)
    cycle_count: float = 0.0

    def update_state(self, dispatch: Dispatch):
        # Apply efficiency on charge only
        delta_energy = \
            self.round_trip_efficiency * dispatch.charge \
            - dispatch.discharge
        delta_state_of_charge = delta_energy / self.storage_capacity
        if delta_state_of_charge > 0.0:
            self.cycle_count += delta_state_of_charge
        self.state_of_charge += delta_state_of_charge

    def dispatch_request(
            self,
            proposal: Dispatch,
            sample_rate: timedelta,
    ) -> Dispatch:
        time_step_hours = sample_rate / timedelta(hours=1)
        dispatch = Dispatch(
            charge=min(
                proposal.charge,
                self.charge_capacity * time_step_hours,
                self.available_storage
            ),
            discharge=min(
                proposal.discharge,
                self.discharge_capacity * time_step_hours,
                self.available_energy,
            )
        )
        self.update_state(dispatch)
        return dispatch


@dataclass
class ThermalStorage(Storage):
    discharge_rate_model: StateBasedProperty
    charge_rate_model: StateBasedProperty
    charging_cop_model: StateBasedProperty
    cycle_count: float = 0.0
    report_on: Tuple[str] = field(default=THERMAL_REPORT_ON, init=False)

    @property
    def discharge_capacity(self):
        return self.discharge_rate_model.calculate(self)

    @property
    def charge_capacity(self):
        return self.charge_rate_model.calculate(self)

    @property
    def charging_cop(self):
        # Todo: update when model is written
        return self.charging_cop_model.calculate(self)

    def update_state(self, dispatch: Dispatch):
        # Todo: update when cop model is written
        # Apply efficiency on charge only
        delta_energy = \
            self.round_trip_efficiency * dispatch.charge \
            - dispatch.discharge
        delta_state_of_charge = delta_energy / self.storage_capacity
        self.state_of_charge += delta_state_of_charge

        if delta_state_of_charge > 0.0:
            self.cycle_count += delta_state_of_charge

    def dispatch_request(self, proposal: Dispatch, sample_rate: timedelta) -> Dispatch:
        time_step_hours = sample_rate / timedelta(hours=1)
        dispatch = Dispatch(
            charge=min(
                proposal.charge,
                self.charge_capacity * time_step_hours,
                self.available_storage
            ),
            discharge=min(
                proposal.discharge,
                self.discharge_capacity * time_step_hours,
                self.available_energy,
            )
        )
        self.update_state(dispatch)
        return dispatch

