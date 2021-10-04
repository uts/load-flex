from portfolio.utils.data_utils import s3BucketManager, CacheManager
import os

from ts_tariffs.sites import ElectricityMeterData, Site
from ts_tariffs.tariffs import TariffRegime

from equipment import Battery
from local_data.local_data import aws_credentials, project_root


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
print(jbs_tariff_regime_data)
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
meter = ElectricityMeterData.from_dataframe(
    'jbs',
    jbs_consump_df,
    column_map
)

jbs_tariff_regime = TariffRegime(jbs_tariff_regime_data)
site = Site(
    'JBS',
    jbs_tariff_regime,
    meter,
)
site.calculate_bill(detailed_bill=False)
for charge, ammount in site.bill.items():
    print(f'Charge: {charge}, Amount {round(ammount, 2):,}')

print(jbs_consump_df['demand_energy'].sum())
print(jbs_consump_df['demand_energy'].mean())
print(jbs_consump_df['demand_apparent'].max())
print(jbs_consump_df['demand_power'].max())
#
# battery = Battery(
#
# )

