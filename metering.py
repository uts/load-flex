from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
import numpy as np
from ts_tariffs.sites import ElectricityMeterData


@dataclass
class PowerFlexMeter(ElectricityMeterData):
    """ ElectricityMeterData with capability to adjust power and apparent
    power based on change in energy demand

    Assumes energy units as kWh
    """

    def adjusted_meter_ts(
            self,
            name,
            new_demand_energy: np.ndarray
    ) -> PowerFlexMeter:
        """ Adjust power, apparent power profiles according to a
         change in demand energy
        """

        new_meter_ts = self.meter_ts.copy()
        new_meter_ts['demand_energy'] = new_demand_energy
        energy_diff = new_demand_energy - self.meter_ts['demand_energy']
        power_diff = energy_diff * self.sample_rate_td / timedelta(hours=1)
        new_meter_ts['demand_power'] += power_diff
        new_meter_ts['demand_apparent'] += power_diff / self.meter_ts['power_factor']

        return PowerFlexMeter(
            name,
            new_meter_ts,
            self.sample_rate,
            self.units
        )
