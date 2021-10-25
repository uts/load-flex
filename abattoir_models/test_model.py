from datetime import timedelta, datetime

from portfolio.utils.data_utils import s3BucketManager, CacheManager
import os

from ts_tariffs.sites import Site, Meters
from ts_tariffs.tariffs import TariffRegime

from controllers import (
    SimpleBatteryTOUShiftController,
    SimpleBatteryPeakShaveController,
    NonChargeHoursCondition,
    NonDischargeHoursCondition,
)
from local_data.local_data import aws_credentials, project_root
from metering import PowerFlexMeter

from storage import Battery
from time_series_utils import PerfectForcaster, Scheduler

from matplotlib import pyplot as plt

bucket_str = 'race-abattoir-load-flex'
cache_folder = os.path.join(project_root, '../local_data/s3_caching')

ab_project_folder = 'C:/Users/114261/Dropbox (UTS ISF)/1. 2021 Projects/21090_RACE_RACE Abattoirs - Fast Track/4. Work in progress/'

cache_manager = CacheManager(
    cache_folder,
    expiration=60 * 60 * 24,
    # expiration=1,
)

bucket_manager = s3BucketManager(
    bucket_str,
    aws_credentials['id'],
    aws_credentials['access_key'],
    cache_manager
)
jbs_folder = ['jbs_data']
jbs_tariff_regime_data = bucket_manager.s3_json_to_dict(
    jbs_folder,
    'jbs_tariff_structure.json'
)

jbs_consump_df = bucket_manager.s3_ftr_to_df(
    ['jbs_data'],
    'electricity_meter.ftr'
)

jbs_consump_df['demand_power'] = jbs_consump_df['Demand (KVA)'] * jbs_consump_df['Power Factor']


column_map = {
    'demand_energy': {
        'ts': 'Consumption (kWh)',
        'units': 'kWh'
    },
    'demand_apparent': {
        'ts': 'Demand (KVA)',
        'units': 'kVa'
    },
    'demand_power': {
        'ts': 'demand_power',
        'units': 'kW'
    },
    'power_factor': {
        'ts': 'Power Factor',
        'units': None
    },
    'generation_energy': {
        'ts': 'Generation (kWh)',
        'units': 'kWh'
        }
}

jbs_consump_df.set_index('datetime', inplace=True)
jbs_consump_df = jbs_consump_df.loc['2021-07-01': '2021-07-31']
meter = PowerFlexMeter.from_dataframe(
    'JBS',
    jbs_consump_df,
    timedelta(minutes=30),
    column_map
)
meters = Meters({meter.name: meter})
jbs_tariff_regime = TariffRegime(jbs_tariff_regime_data)
site = Site(
    'JBS',
    jbs_tariff_regime,
    meters,
)

forecaster = PerfectForcaster(timedelta(hours=24))
scheduler = Scheduler(datetime(2021, 7, 1, 7), timedelta(hours=24))

battery = Battery(
    'battery',
    2000,
    2000,
    50_000,
    1.0,
    state_of_charge=1.0,
)
dispatch_conditions = [
    NonChargeHoursCondition(tuple(range(7, 22))),
    NonDischargeHoursCondition(tuple(range(22, 24))),
    NonDischargeHoursCondition(tuple(range(0, 7)))
]
controller = SimpleBatteryTOUShiftController(
    'battery controller',
    battery,
    forecaster,
    scheduler,
    dispatch_conditions,
    meter,
    dispatch_on='demand_energy'
)

controller.dispatch()
site.add_meter(
    meter.calculate_flexed_demand(
        'JBS_flexed',
        return_new_meter=True,
    )
)

plt.plot(site.meters['JBS'].tseries['demand_energy'])
plt.plot(site.meters['JBS_flexed'].tseries['demand_energy'])
plt.plot(site.meters['JBS'].dispatch_ts['dispatch_threshold'])
plt.show()


site.calculate_bill()
for bill_name, bill in site.bills.items():
    for charge, amount in bill.itemised_totals.items():
        print(f'Charge: {charge}, Amount {round(amount, 2):,}')


