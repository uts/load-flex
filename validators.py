from typing import Tuple

import numpy as np


class Validator:
    @staticmethod
    def type_check(name, obj, valid_types: tuple):
        if not isinstance(obj, valid_types):
            valid_types_str = ', '.join(valid_types)
            raise TypeError(f'{name} must be type/s: {valid_types_str}')

    @staticmethod
    def data_cols(df, mandatory_cols: tuple):
        not_present = list([col not in df.columns for col in mandatory_cols])
        if any(not_present):
            content = ', '.join(np.array(mandatory_cols)[not_present])
            raise ValueError(f'The following columns must be present in dataframe: {content}')

    @staticmethod
    def string_options(attr_str: str, value_str: str, options: Tuple[str]):
        if value_str not in options:
            raise ValueError(f'Invalid string value "{value_str}": {attr_str} must be one of the following: {options}')