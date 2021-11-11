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
class PCMStorageStateBasedDischargeCapacity(StateBasedProperty):
    inlet_temp: float
    outlet_temp: float
    pcm_melt_temp: float
    density: float
    specific_heat_capacity: float
    design_flow_rate: float

    def calculate(self, state: Storage) -> float:
        effectiveness = pcm_calcs.system_effectiveness(
            self.inlet_temp,
            self.outlet_temp,
            self.pcm_melt_temp
        )
        normalised_flow = pcm_calcs.normalised_flow_rate(
            effectiveness,
            state.state_of_charge
        )
        return pcm_calcs.max_discharge_rate(
            self.design_flow_rate,
            normalised_flow,
            self.density,
            self.specific_heat_capacity,
            self.inlet_temp,
            self.pcm_melt_temp,
            effectiveness
        )
