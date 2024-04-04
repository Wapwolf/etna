import re
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from etna.analysis import get_anomalies_density
from etna.analysis import get_anomalies_median
from etna.analysis import get_anomalies_prediction_interval
from etna.datasets.tsdataset import TSDataset
from etna.models import ProphetModel
from etna.models import SARIMAXModel
from etna.transforms import DensityOutliersTransform
from etna.transforms import HolidayTransform
from etna.transforms import MedianOutliersTransform
from etna.transforms import PredictionIntervalOutliersTransform
from tests.test_transforms.utils import assert_column_changes
from tests.test_transforms.utils import assert_sampling_is_valid
from tests.test_transforms.utils import assert_transformation_equals_loaded_original
from tests.test_transforms.utils import find_columns_diff
from tests.utils import select_segments_subset


@pytest.fixture()
def outliers_solid_tsds():
    """Create TSDataset with outliers and same last date."""
    timestamp = pd.date_range("2021-01-01", end="2021-02-20", freq="D")
    target1 = [np.sin(i) for i in range(len(timestamp))]
    target1[10] += 10

    target2 = [np.sin(i) for i in range(len(timestamp))]
    target2[8] += 8
    target2[15] = 2
    target2[26] -= 12

    df1 = pd.DataFrame({"timestamp": timestamp, "target": target1, "segment": "1"})
    df2 = pd.DataFrame({"timestamp": timestamp, "target": target2, "segment": "2"})
    df = pd.concat([df1, df2], ignore_index=True)
    df_exog = df.copy()
    df_exog.columns = ["timestamp", "regressor_1", "segment"]
    ts = TSDataset(
        df=TSDataset.to_dataset(df).iloc[:-10],
        df_exog=TSDataset.to_dataset(df_exog),
        freq="D",
        known_future="all",
    )
    return ts


@pytest.fixture()
def outliers_solid_tsds_with_holidays():
    """Create TSDataset with outliers with holidays"""
    timestamp = pd.date_range("2021-01-01", end="2021-02-20", freq="D")
    target1 = [np.sin(i) for i in range(len(timestamp))]
    target1[10] += 10

    target2 = [np.sin(i) for i in range(len(timestamp))]
    target2[8] += 8
    target2[15] = 2
    target2[26] -= 12

    df1 = pd.DataFrame({"timestamp": timestamp, "target": target1, "segment": "1"})
    df2 = pd.DataFrame({"timestamp": timestamp, "target": target2, "segment": "2"})
    df = pd.concat([df1, df2], ignore_index=True)
    df_exog = df.copy()
    df_exog.columns = ["timestamp", "regressor_1", "segment"]
    ts = TSDataset(
        df=TSDataset.to_dataset(df).iloc[:-10],
        df_exog=TSDataset.to_dataset(df_exog),
        freq="D",
        known_future="all",
    )
    holiday_transform = HolidayTransform(iso_code="RUS", mode="binary", out_column="is_holiday")
    ts = holiday_transform.fit_transform(ts)
    return ts


@pytest.fixture()
def outliers_solid_tsds_with_error():
    """Create TSDataset with outliers error inside ts, incorrect type column"""
    timestamp = pd.date_range("2021-01-01", end="2021-02-20", freq="D")
    target1 = [np.sin(i) for i in range(len(timestamp))]
    target1[5] += 10
    info_col1 = [1 if np.sin(i) > 0.5 else 0 for i in range(len(timestamp))]
    info_col1[9] = 4

    target2 = [np.sin(i) for i in range(len(timestamp))]
    target2[8] += 8
    target2[15] = 2
    target2[26] -= 12
    info_col2 = [1 if np.sin(i) > 0 else 0 for i in range(len(timestamp))]
    info_col2[10] = 14

    df1 = pd.DataFrame({"timestamp": timestamp, "target": target1, "segment": "1", "is_holiday": info_col1})
    df2 = pd.DataFrame({"timestamp": timestamp, "target": target2, "segment": "2", "is_holiday": info_col2})
    df = pd.concat([df1, df2], ignore_index=True)
    df_exog = df.copy()
    df_exog.columns = ["timestamp", "regressor_1", "segment", "is_holiday"]
    ts = TSDataset(
        df=TSDataset.to_dataset(df[["timestamp", "target", "segment"]]).iloc[:-10],
        df_exog=TSDataset.to_dataset(df_exog),
        freq="D",
        known_future="all",
    )
    return ts


@pytest.fixture()
def outliers_solid_tsds_for_pipeline():
    """Create TSDataset with outliers error inside ts, incorrect type column"""
    timestamp = pd.date_range("2021-01-01", end="2021-02-20", freq="D")
    target1 = [np.sin(i) for i in range(len(timestamp))]
    target1[5] += 10
    info_col1 = [1 if np.sin(i) > 0.5 else 0 for i in range(len(timestamp))]

    target2 = [np.sin(i) for i in range(len(timestamp))]
    target2[8] += 8
    target2[15] = 2
    target2[26] -= 12
    info_col2 = [1 if np.sin(i) > 0 else 0 for i in range(len(timestamp))]

    df1 = pd.DataFrame({"timestamp": timestamp, "target": target1, "segment": "1", "is_holiday": info_col1})
    df2 = pd.DataFrame({"timestamp": timestamp, "target": target2, "segment": "2", "is_holiday": info_col2})
    df = pd.concat([df1, df2], ignore_index=True)
    df_exog = df.copy()
    df_exog.columns = ["timestamp", "regressor_1", "segment", "is_holiday"]
    ts = TSDataset(
        df=TSDataset.to_dataset(df[["timestamp", "target", "segment"]]).iloc[:-10],
        df_exog=TSDataset.to_dataset(df_exog),
        freq="D",
        known_future="all",
    )
    return ts


@pytest.mark.parametrize("attribute_name,value_type", (("outliers_timestamps", list), ("original_values", pd.Series)))
def test_density_outliers_deprecated_store_attributes(outliers_solid_tsds, attribute_name, value_type):
    transform = DensityOutliersTransform(in_column="target")
    transform.fit(ts=outliers_solid_tsds)

    with pytest.warns(DeprecationWarning, match=".* is deprecated and will be removed"):
        res = getattr(transform, attribute_name)

    assert isinstance(res, dict)
    for key, value in res.items():
        assert isinstance(key, str)
        assert isinstance(value, value_type)


@pytest.mark.parametrize("in_column", ["target", "regressor_1"])
@pytest.mark.parametrize(
    "transform_constructor, constructor_kwargs",
    [
        (MedianOutliersTransform, {}),
        (DensityOutliersTransform, {}),
        (PredictionIntervalOutliersTransform, dict(model=ProphetModel)),
    ],
)
def test_interface(transform_constructor, constructor_kwargs, outliers_solid_tsds: TSDataset, in_column):
    """Checks outliers transforms doesn't change structure of dataframe."""
    transform = transform_constructor(in_column=in_column, **constructor_kwargs)
    start_columns = outliers_solid_tsds.columns
    outliers_solid_tsds = transform.fit_transform(ts=outliers_solid_tsds)
    assert np.all(start_columns == outliers_solid_tsds.columns)


@pytest.mark.parametrize("in_column", ["target", "exog"])
@pytest.mark.parametrize(
    "transform_constructor, constructor_kwargs, method, method_kwargs",
    [
        (MedianOutliersTransform, {}, get_anomalies_median, {}),
        (DensityOutliersTransform, {}, get_anomalies_density, {}),
        (
            PredictionIntervalOutliersTransform,
            dict(model=ProphetModel),
            get_anomalies_prediction_interval,
            dict(model=ProphetModel),
        ),
    ],
)
def test_outliers_detection(transform_constructor, constructor_kwargs, method, outliers_tsds, method_kwargs, in_column):
    """Checks that outliers transforms detect anomalies according to methods from etna.analysis."""
    detection_method_results = method(outliers_tsds, in_column=in_column, **method_kwargs)
    transform = transform_constructor(in_column=in_column, **constructor_kwargs)

    # save for each segment index without existing nans
    non_nan_index = {}
    for segment in outliers_tsds.segments:
        non_nan_index[segment] = outliers_tsds[:, segment, in_column].dropna().index
    # convert to df to ignore different lengths of series
    transformed_df = transform.fit_transform(outliers_tsds).to_pandas()
    for segment in outliers_tsds.segments:
        nan_timestamps = detection_method_results[segment]
        transformed_column = transformed_df.loc[non_nan_index[segment], pd.IndexSlice[segment, in_column]]
        assert np.all(transformed_column[transformed_column.isna()].index == nan_timestamps)


@pytest.mark.parametrize("in_column", ["target", "regressor_1"])
@pytest.mark.parametrize(
    "transform_constructor, constructor_kwargs",
    [
        (MedianOutliersTransform, {}),
        (DensityOutliersTransform, {}),
        (PredictionIntervalOutliersTransform, dict(model=ProphetModel)),
    ],
)
def test_inverse_transform_train(transform_constructor, constructor_kwargs, outliers_solid_tsds, in_column):
    """Checks that inverse transform returns dataset to its original form."""
    transform = transform_constructor(in_column=in_column, **constructor_kwargs)
    original_df = outliers_solid_tsds.to_pandas()
    outliers_solid_tsds = transform.fit_transform(ts=outliers_solid_tsds)
    transform.inverse_transform(ts=outliers_solid_tsds)

    assert np.all(original_df == outliers_solid_tsds.df)


@pytest.mark.parametrize("in_column", ["target", "regressor_1"])
@pytest.mark.parametrize(
    "transform_constructor, constructor_kwargs",
    [
        (MedianOutliersTransform, {}),
        (DensityOutliersTransform, {}),
        (PredictionIntervalOutliersTransform, dict(model=ProphetModel)),
    ],
)
def test_inverse_transform_future(transform_constructor, constructor_kwargs, outliers_solid_tsds, in_column):
    """Checks that inverse transform does not change the future."""
    transform = transform_constructor(in_column=in_column, **constructor_kwargs)
    outliers_solid_tsds.fit_transform([transform])
    future = outliers_solid_tsds.make_future(future_steps=10, transforms=[transform])
    original_future_df = future.to_pandas()
    future.inverse_transform([transform])
    # check equals and has nans in the same places
    assert np.all((future.df == original_future_df) | (future.df.isna() & original_future_df.isna()))


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target"),
        DensityOutliersTransform(in_column="target"),
        PredictionIntervalOutliersTransform(in_column="target", model=ProphetModel),
    ),
)
def test_transform_raise_error_if_not_fitted(transform, outliers_solid_tsds):
    """Test that transform for one segment raise error when calling transform without being fit."""
    with pytest.raises(ValueError, match="Transform is not fitted!"):
        _ = transform.transform(ts=outliers_solid_tsds)


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target"),
        DensityOutliersTransform(in_column="target"),
        PredictionIntervalOutliersTransform(in_column="target", model=ProphetModel),
    ),
)
def test_inverse_transform_raise_error_if_not_fitted(transform, outliers_solid_tsds):
    """Test that transform for one segment raise error when calling inverse_transform without being fit."""
    with pytest.raises(ValueError, match="Transform is not fitted!"):
        _ = transform.inverse_transform(ts=outliers_solid_tsds)


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target"),
        DensityOutliersTransform(in_column="target"),
        PredictionIntervalOutliersTransform(in_column="target", model=ProphetModel),
    ),
)
def test_transform_new_segments_fail(transform, outliers_solid_tsds):
    train_ts = select_segments_subset(ts=outliers_solid_tsds, segments=["1"])
    test_ts = select_segments_subset(ts=outliers_solid_tsds, segments=["2"])

    transform.fit(train_ts)
    with pytest.raises(
        NotImplementedError, match="This transform can't process segments that weren't present on train data"
    ):
        _ = transform.transform(test_ts)


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target"),
        DensityOutliersTransform(in_column="target"),
        PredictionIntervalOutliersTransform(in_column="target", model=ProphetModel),
    ),
)
def test_inverse_transform_new_segments_fail(transform, outliers_solid_tsds):
    train_ts = select_segments_subset(ts=outliers_solid_tsds, segments=["1"])
    test_ts = select_segments_subset(ts=outliers_solid_tsds, segments=["2"])

    transform.fit(train_ts)
    with pytest.raises(
        NotImplementedError, match="This transform can't process segments that weren't present on train data"
    ):
        _ = transform.inverse_transform(test_ts)


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target"),
        DensityOutliersTransform(in_column="target"),
        PredictionIntervalOutliersTransform(in_column="target", model=ProphetModel),
    ),
)
def test_fit_transform_with_nans(transform, ts_diff_endings):
    _ = transform.fit_transform(ts_diff_endings)


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target"),
        DensityOutliersTransform(in_column="target"),
    ),
)
def test_save_load(transform, outliers_solid_tsds):
    assert_transformation_equals_loaded_original(transform=transform, ts=outliers_solid_tsds)


@pytest.mark.parametrize(
    "transform",
    (
        PredictionIntervalOutliersTransform(in_column="target", model=ProphetModel),
        PredictionIntervalOutliersTransform(in_column="target", model=SARIMAXModel),
    ),
)
def test_save_load_prediction_interval(transform, outliers_solid_tsds):
    assert_transformation_equals_loaded_original(transform=transform, ts=outliers_solid_tsds)


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target"),
        DensityOutliersTransform(in_column="target"),
        PredictionIntervalOutliersTransform(in_column="target", model="sarimax"),
    ),
)
def test_params_to_tune(transform, outliers_solid_tsds):
    ts = outliers_solid_tsds
    assert len(transform.params_to_tune()) > 0
    assert_sampling_is_valid(transform=transform, ts=ts)


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target", ignore_flag_column="is_holiday"),
        DensityOutliersTransform(in_column="target", ignore_flag_column="is_holiday"),
        PredictionIntervalOutliersTransform(in_column="target", model="sarimax", ignore_flag_column="is_holiday"),
    ),
)
def test_correct_ignore_flag(transform, outliers_solid_tsds_with_holidays):
    ts = outliers_solid_tsds_with_holidays
    assert len(transform.params_to_tune()) > 0
    transform.fit(ts)
    ts_output = transform.transform(ts)
    assert not all(ts_output["2021-01-06":"2021-01-06", "1", "target"].isna())


@pytest.mark.parametrize(
    "transform",
    (
        MedianOutliersTransform(in_column="target", ignore_flag_column="is_holiday"),
        DensityOutliersTransform(in_column="target", ignore_flag_column="is_holiday"),
        PredictionIntervalOutliersTransform(in_column="target", model="sarimax", ignore_flag_column="is_holiday"),
    ),
)
def test_incorrect_not_exists_column(transform, outliers_solid_tsds):
    ts = outliers_solid_tsds
    assert len(transform.params_to_tune()) > 0
    with pytest.raises(ValueError, match='Name ignore_flag_column="is_holiday" not find.'):
        transform.fit(ts)
        _ = transform.transform(ts)


@pytest.mark.parametrize(
    "transform",
    (
            MedianOutliersTransform(in_column="target", ignore_flag_column="is_holiday"),
            DensityOutliersTransform(in_column="target", ignore_flag_column="is_holiday"),
            PredictionIntervalOutliersTransform(in_column="target", model="sarimax",
                                                ignore_flag_column="is_holiday"),
    ),
)
def test_incorrect_type_ignore_flag(transform, outliers_solid_tsds_with_error):
    ts = outliers_solid_tsds_with_error
    with pytest.raises(
        ValueError,
        match=re.escape("Columns ignore_flag contain non binary value: columns: \"is_holiday\" in segment: ['1', '2']"),
    ):
        transform.fit(ts)
        _ = transform.transform(ts)


@pytest.mark.parametrize(
    "transform, expected_changes",
    [
        (MedianOutliersTransform(in_column="target", ignore_flag_column="is_holiday"), {"change": {"target"}}),
        (DensityOutliersTransform(in_column="target", ignore_flag_column="is_holiday"), {"change": {"target"}}),
        (
            PredictionIntervalOutliersTransform(in_column="target", model="sarimax", ignore_flag_column="is_holiday"),
            {"change": {"target"}},
        ),
    ],
)
def test_full_pipeline(transform, expected_changes, outliers_solid_tsds_for_pipeline):
    ts = outliers_solid_tsds_for_pipeline

    train_ts = deepcopy(ts)
    test_ts = deepcopy(ts)

    transform.fit(train_ts)

    transformed_test_ts = transform.transform(deepcopy(test_ts))

    inverse_transformed_test_ts = transform.inverse_transform(deepcopy(transformed_test_ts))

    # check
    assert_column_changes(ts_1=transformed_test_ts, ts_2=inverse_transformed_test_ts, expected_changes=expected_changes)
    flat_test_df = test_ts.to_pandas(flatten=True)
    flat_transformed_test_df = transformed_test_ts.to_pandas(flatten=True)
    flat_inverse_transformed_test_df = inverse_transformed_test_ts.to_pandas(flatten=True)
    created_columns, removed_columns, changed_columns = find_columns_diff(
        flat_transformed_test_df, flat_inverse_transformed_test_df
    )
    pd.testing.assert_frame_equal(
        flat_test_df[list(changed_columns)], flat_inverse_transformed_test_df[list(changed_columns)]
    )
