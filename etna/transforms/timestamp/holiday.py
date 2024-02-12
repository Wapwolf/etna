import itertools
from datetime import datetime
from datetime import timedelta
from enum import Enum
from typing import List
from typing import Optional

import holidays
import numpy as np
import pandas as pd

from etna.transforms.base import IrreversibleTransform


class HolidayTransformMode(str, Enum):
    """Enum for different imputation strategy."""

    binary = "binary"
    category = "category"
    days_count = "days_count"

    @classmethod
    def _missing_(cls, value):
        raise NotImplementedError(
            f"{value} is not a valid {cls.__name__}. Supported mode: {', '.join([repr(m.value) for m in cls])}"
        )


class HolidayTransform(IrreversibleTransform):
    """
    HolidayTransform generates series that indicates holidays in given dataset.

    In `binary` mode shows the presence of holiday in that day. In `category` mode shows the name of the holiday
    with value "NO_HOLIDAY" reserved for days without holidays.
    """

    _no_holiday_name: str = "NO_HOLIDAY"

    def __init__(self, iso_code: str = "RUS", mode: str = "binary", out_column: Optional[str] = None):
        """
        Create instance of HolidayTransform.

        Parameters
        ----------
        iso_code:
            internationally recognised codes, designated to country for which we want to find the holidays
        mode:
            binary to indicate holidays, category to specify which holiday do we have at each day
        out_column:
            name of added column. Use `self.__repr__()` if not given.
        """
        super().__init__(required_features=["target"])
        self.iso_code = iso_code
        self.mode = mode
        self._mode = HolidayTransformMode(mode)
        self.holidays = holidays.country_holidays(iso_code)
        self.out_column = out_column

    def _get_column_name(self) -> str:
        if self.out_column:
            return self.out_column
        else:
            return self.__repr__()

    def _fit(self, df: pd.DataFrame) -> "HolidayTransform":
        """
        Fit HolidayTransform with data from df. Does nothing in this case.

        Parameters
        ----------
        df: pd.DataFrame
            value series with index column in timestamp format
        """
        return self

    def _transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform data from df with HolidayTransform and generate a column of holidays flags or its titles.
        In days_count mode calculates the frequency of holidays in a given period of time

        Parameters
        ----------
        df: pd.DataFrame
            value series with index column in timestamp format

        Returns
        -------
        :
            pd.DataFrame with added holidays
        """
        inferred_freq = pd.infer_freq(df.index)
        if inferred_freq != "D" and self._mode is not HolidayTransformMode.days_count:
            raise ValueError("In default mode frequency of data should be no more than daily.")

        cols = df.columns.get_level_values("segment").unique()
        out_column = self._get_column_name()

        if self._mode is HolidayTransformMode.days_count:
            encoded_matrix = np.empty(0)
            for date in df.index:
                numbers_part = "".join(itertools.takewhile(str.isdigit, inferred_freq))
                letters_part = "".join(itertools.dropwhile(str.isdigit, inferred_freq))
                numbers_part = "1" if numbers_part == "" else numbers_part
                start_date = datetime(2011, 1, 1)
                new_date = datetime(2011, 1, 1)
                if letters_part == "W":
                    start_date = date - timedelta(days=date.weekday())
                    new_date = start_date + pd.DateOffset(weeks=int(numbers_part))
                elif letters_part in ["M", "MS"]:
                    start_date = date.replace(day=1)
                    new_date = start_date + pd.DateOffset(months=int(numbers_part))
                elif letters_part in ["Q-DEC", "QS-OCT", "QS-DEC", "QS-OST"]:
                    start_date = date.replace(day=1)
                    new_date = start_date + pd.DateOffset(months=3 * int(numbers_part))
                elif letters_part in ["A-DEC", "AS-JAN"]:
                    start_date = date.replace(month=1, day=1)
                    new_date = start_date + pd.DateOffset(years=int(numbers_part))
                else:
                    raise ValueError("days_count mode don't support frequency less than Weekly")
                date_range = pd.date_range(start=start_date, end=(new_date - timedelta(days=1)), freq="d")
                count_holidays = sum(1 for d in date_range if d in self.holidays)
                holidays_freq = count_holidays / date_range.size
                encoded_matrix = np.append(encoded_matrix, holidays_freq)
        elif self._mode is HolidayTransformMode.category:
            encoded_matrix = np.array(
                [self.holidays[x] if x in self.holidays else self._no_holiday_name for x in df.index]
            )
        else:
            encoded_matrix = np.array([int(x in self.holidays) for x in df.index])
        encoded_matrix = encoded_matrix.reshape(-1, 1).repeat(len(cols), axis=1)
        encoded_df = pd.DataFrame(
            encoded_matrix,
            columns=pd.MultiIndex.from_product([cols, [out_column]], names=("segment", "feature")),
            index=df.index,
        )
        if self._mode is HolidayTransformMode.days_count:
            encoded_df = encoded_df.astype("category")
        df = df.join(encoded_df)
        df = df.sort_index(axis=1)
        return df

    def get_regressors_info(self) -> List[str]:
        """Return the list with regressors created by the transform.
        Returns
        -------
        :
            List with regressors created by the transform.
        """
        return [self._get_column_name()]
