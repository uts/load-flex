import numpy as np


class PCMThermalStoragePerformance:
    @staticmethod
    def system_effectiveness(
            inlet_temp: float,
            outlet_temp: float,
            pcm_melt_temp: float
    ) -> float:
        """
        The outlet temperature from the PCM system determines the
        heat transferred between the heat transfer fluid and the
        PCM and consequently, thermal performance can be expressed
        in terms of a heat exchange effectiveness. This effectiveness
        directly relates to the thermal resistance in the PCM
        storage system. If the heat transfer rate does
        not vary with time, the effectiveness of a PCM storage
        system is defined by;
         effectiveness =  (Tin - Tout) / (Tin - Tpcm) = Qactual / Qmax
        See - https://www.sciencedirect.com/science/article/pii/S0038092X12001697
        """
        return (inlet_temp - outlet_temp) / (inlet_temp - pcm_melt_temp)

    @staticmethod
    def charging_effectiveness(state_of_charge):
        """ Regression based calculation

        Regression relationship is based on empirical data:
            ε=co+c1×f+c2×f^2+c3×f^3+c4×f^4
            f = state of charge
        """
        c0 = 0.520491903
        c1 = 6.204005154
        c2 = -29.92330103
        c3 = 46.56089333
        c4 = -23.82942879
        return (
                    c0 +
                    c1 * state_of_charge +
                    c2 * state_of_charge ** 2 +
                    c3 * state_of_charge ** 3 +
                    c4 * state_of_charge ** 4
                )

    @staticmethod
    def normalised_flow_rate(
            effectiveness: float,
            state_of_charge: float
    ) -> float:
        """ Regression based calculation of normalised flow rate
        (i.e. actual flow / design flow). Relies on effectiveness rate ε,
        state of charge f and regression coefficients

        Regression relationship is based on empirical data:
            ε=co+c1×f+c2×n+c3×f×n+c4×f^2+c5×f^3+c6×f^4
            n = normalised flow rate
            f = state of charge

        returns: n=(ε-(co+c1×f+c4×f^2+c5×f^3+c6×f^4))/(c2+c3×f)
        """
        c0 = 0.728269761
        c1 = 3.252826183
        c2 = -0.262047961
        c3 = -0.086927382
        c4 = - 14.54832594
        c5 = 21.21098192
        c6 = - 9.407503243
        n = (effectiveness - (
                c0 +
                c1 * state_of_charge +
                c4 * pow(state_of_charge, 2) +
                c5 * pow(state_of_charge, 3) +
                c6 * pow(state_of_charge, 4)
        )
        ) \
            / (c2 + c3 * state_of_charge)
        # Throttle between 1.25 and 0.25
        return np.clip(n, 0.20, 1.25)

    @staticmethod
    def flow_rate(
            design_flow_rate: float,
            normalised_flow_rate: float,
    ) -> float:
        return design_flow_rate * normalised_flow_rate

    @staticmethod
    def max_heat_exchange_rate(
            flow_rate,
            density,
            specific_heat_capacity: float,
            inlet_temp: float,
            pcm_melt_temp: float,
            effectiveness: float
    ) -> float:
        """
        """
        return effectiveness * \
            flow_rate * \
            density * \
            specific_heat_capacity * \
            (inlet_temp - pcm_melt_temp)
