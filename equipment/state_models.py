from abc import abstractmethod, ABC
from dataclasses import dataclass

from equipment.equipment import Equipment
from equipment.equipment import Storage
from equipment.perfomance_relationships import PCMThermalStoragePerformance as pcm_calcs


@dataclass
class StateBasedProperty(ABC):
    @abstractmethod
    def calculate(self, state: Equipment):
        pass


@dataclass
class StateBasedCOP(StateBasedProperty):
    def calculate(self, state: Equipment) -> float:
        # Todo: insert model here
        return 4.0


@dataclass
class StateBasedCapacity(StateBasedProperty):
    nominal_capacity: float

    @abstractmethod
    def calculate(self, state: Equipment) -> float:
        pass


@dataclass
class SpoofCapacity(StateBasedProperty):
    spoof_value: float

    def calculate(self, state: Equipment):
        return self.spoof_value

@dataclass
class PCMDischargeCapacity(StateBasedProperty):
    inlet_temp: float
    outlet_temp: float
    pcm_melt_temp: float
    density: float
    specific_heat_capacity: float
    design_flow_rate: float

    @property
    def target_effectiveness(self):

        return pcm_calcs.system_effectiveness(
            self.inlet_temp,
            self.outlet_temp,
            self.pcm_melt_temp
        )

    def normalised_flow(self, state: Storage) -> float:
        return pcm_calcs.normalised_flow_rate(
            self.target_effectiveness,
            state.state_of_charge
        )

    def calculate(self, state: Storage) -> float:
        normalised_flow_rate = self.normalised_flow(state)
        capacity = pcm_calcs.max_heat_exchange_rate(
            normalised_flow_rate * self.design_flow_rate,
            self.density,
            self.specific_heat_capacity,
            self.inlet_temp,
            self.pcm_melt_temp,
            self.target_effectiveness
        )
        return capacity


@dataclass
class PCMChargeCapacity(StateBasedProperty):
    inlet_temp: float
    outlet_temp: float
    pcm_melt_temp: float
    density: float
    specific_heat_capacity: float
    design_flow_rate: float

    def calculate(self, state: Storage) -> float:
        if 0.0 <= state.state_of_charge <= 0.15:
            effectiveness = 1.0
        elif 0.85 < state.state_of_charge:
            effectiveness = 0.2
        else:
            effectiveness = pcm_calcs.charging_effectiveness(
                state.state_of_charge
            )
        return - pcm_calcs.max_heat_exchange_rate(
            self.design_flow_rate,
            self.density,
            self.specific_heat_capacity,
            self.inlet_temp,
            self.pcm_melt_temp,
            effectiveness
        )
