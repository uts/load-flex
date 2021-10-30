from abc import ABC
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class SetPointOptimiser(ABC):
    pass


@dataclass
class PeakShave(SetPointOptimiser):
    @staticmethod
    def cumulative_peak_areas(sorted_arr: np.ndarray):
        delta_energy = np.append(np.diff(sorted_arr), 0)
        reverse_index = np.array(range(len(sorted_arr) - 1, -1, -1))
        delta_area = delta_energy * reverse_index
        return np.cumsum(np.flip(delta_area))

    @staticmethod
    def peak_area_idx(peak_areas, area, max_idx=None):
        idx = np.searchsorted(peak_areas, area) - 1
        if max_idx:
            return min(idx, max_idx)
        else:
            return idx

    @staticmethod
    def sub_load_peak_shave_limit(
            sorted_df: pd.DataFrame,
            max_idx: int,
            area: float,
            gross_col: str,
            sub_col: str,
    ) -> float:
        for i, row in sorted_df.iloc[:max_idx:-1].iterrows():
            exposed_gross = sorted_df[gross_col].values - row[gross_col]
            exposed_gross = np.where(exposed_gross < 0, 0, exposed_gross)
            exposed_sub = np.clip(sorted_df[sub_col].values, 0, exposed_gross)
            exposed_sub_area = sum(exposed_sub)
            if exposed_sub_area >= area:
                return sorted_df[gross_col].iloc[i + 1]
        return 0.0

    @staticmethod
    def peak_shave(demand_arr: np.ndarray, area):
        sorted_arr = np.sort(demand_arr)
        peak_areas = PeakShave.cumulative_peak_areas(sorted_arr)
        index = PeakShave.peak_area_idx(
            peak_areas,
            area
        )
        return np.flip(sorted_arr)[index]

@dataclass
class TOUShiftingCalculator(SetPointOptimiser):
    @staticmethod
    def inverted_arr(arr):
        """ Flip array vertically such that troughs become peaks
        and the flipped peak is equal to the un-flipped peak
        """
        return arr.max() - arr


    @staticmethod
    def cap_area(arr: np.ndarray):
        cap_arr = arr - arr.min()
        return cap_arr.sum()

    @staticmethod
    def cap_height(arr: np.ndarray):
        cap_arr = arr - arr.min()
        return cap_arr.max()

    @staticmethod
    def additional_depth(arr: np.ndarray, area_required: float):
        width = len(arr)
        return area_required / width

    @staticmethod
    def calculate_setpoint(demand_arr: np.ndarray, area: float):
        setpoint = demand_arr.max()
        if area:
            cap_area = TOUShiftingCalculator.cap_area(demand_arr)
            additional_area_required = area - cap_area
            if additional_area_required > 0.0:
                additional_depth_required = TOUShiftingCalculator.additional_depth(
                    demand_arr,
                    additional_area_required
                )
                total_depth = \
                    additional_depth_required + TOUShiftingCalculator.cap_height(demand_arr)
                setpoint = demand_arr.max() - total_depth
            else:
                setpoint = PeakShave.peak_shave(demand_arr, area)
        return setpoint

    @staticmethod
    def charge_setpoint(demand_arr: np.ndarray, area: float):
        inverted_arr = TOUShiftingCalculator.inverted_arr(demand_arr)
        return demand_arr.max() - TOUShiftingCalculator.calculate_setpoint(
            inverted_arr,
            area
        )
