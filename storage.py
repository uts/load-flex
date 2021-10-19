from dataclasses import dataclass, field
from typing import Tuple

from equipment import Storage
from state_models import StateBasedProperty

REPORT_ON = (
        'state_of_charge',
        'available_energy',
        'available_storage'
    )
THERMAL_REPORT_ON = (
        'discharge_capacity',
        'charge_capacity',
        'charging_cop',
        *REPORT_ON
    )


@dataclass
class Battery(Storage):
    report_on: Tuple[str] = field(default=REPORT_ON, init=False)

    def update_state(self, energy: float):
        if energy > 0:
            # Apply efficiency on charge only
            energy = self.round_trip_efficiency * energy
        self.state_of_charge += energy / self.storage_capacity

    def energy_request(self, energy) -> float:
        # Negative energy indicates discharge
        # Positive energy indicate charge
        if energy < 0:
            energy_exchange = - min(
                abs(energy),
                self.nominal_discharge_capacity,
                self.available_energy
            )
        else:
            energy_exchange = min(
                energy,
                self.available_storage,
                self.nominal_charge_capacity
            )
        self.update_state(energy_exchange)
        return energy_exchange


@dataclass
class ThermalStorage(Storage):
    discharge_rate_model: StateBasedProperty
    charge_rate_model: StateBasedProperty
    charging_cop_model: StateBasedProperty
    hot_reservoir_temperature: float
    report_on: Tuple[str] = field(default=THERMAL_REPORT_ON, init=False)

    @property
    def discharge_capacity(self):
        # Todo: update when model is written
        return self.discharge_rate_model.calculate(self)

    @property
    def charge_capacity(self):
        # Todo: update when model is written
        return self.charge_rate_model.calculate(self)

    @property
    def charging_cop(self):
        # Todo: update when model is written
        return self.charging_cop_model.calculate(self)

    def update_state(self, energy):
        if energy > 0:
            # Apply efficiency on charge only
            energy = self.round_trip_efficiency * energy
        self.state_of_charge += energy / self.storage_capacity

    def energy_request(self, energy) -> float:
        # Negative energy indicates discharge
        # Positive energy indicate charge
        if energy < 0:
            energy_exchange = - min(
                abs(energy),
                self.nominal_discharge_capacity,
                self.available_energy
            )
        else:
            energy_exchange = min(
                energy,
                self.available_storage,
                self.nominal_charge_capacity
            )
        self.update_state(energy_exchange)
        return energy_exchange
