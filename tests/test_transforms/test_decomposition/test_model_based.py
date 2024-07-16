import numpy as np
import pandas as pd
import pytest

from etna.datasets import TSDataset
from etna.datasets import generate_ar_df
from etna.metrics import MAE
from etna.models import BATSModel
from etna.models import CatBoostPerSegmentModel
from etna.models import DeadlineMovingAverageModel
from etna.models import HoltWintersModel
from etna.models import ProphetModel
from etna.models import SARIMAXModel
from etna.models import SeasonalMovingAverageModel
from etna.models import TBATSModel
from etna.pipeline import Pipeline
from etna.transforms import IForestOutlierTransform
from etna.transforms import ModelDecomposeTransform
from etna.transforms import TimeSeriesImputerTransform


def simple_pipeline_with_decompose(in_column, horizon):
    pipeline = Pipeline(
        transforms=[ModelDecomposeTransform(model=HoltWintersModel(), in_column=in_column)],
        model=HoltWintersModel(),
        horizon=horizon,
    )
    return pipeline


@pytest.fixture()
def ts_with_exog() -> TSDataset:
    periods = 100
    periods_exog = periods + 10
    df = generate_ar_df(start_time="2020-01-01", periods=periods, freq="D", n_segments=2)
    df_exog = generate_ar_df(start_time="2020-01-01", periods=periods_exog, freq="D", n_segments=2, random_seed=2)
    df_exog.rename(columns={"target": "exog"}, inplace=True)
    df_exog["holiday"] = np.random.choice([0, 1], size=periods_exog * 2)

    df = TSDataset.to_dataset(df)
    df_exog = TSDataset.to_dataset(df_exog)
    ts = TSDataset(df, freq="D", df_exog=df_exog, known_future="all")
    return ts


@pytest.fixture()
def ts_with_exog_train_test(ts_with_exog):
    return ts_with_exog.train_test_split(test_size=20)


@pytest.fixture()
def forward_stride_datasets(ts_with_exog):
    train_df = ts_with_exog.df.iloc[:-10]
    test_df = ts_with_exog.df.iloc[-20:]

    train_ts = TSDataset(df=train_df, freq=ts_with_exog.freq)
    test_ts = TSDataset(df=test_df, freq=ts_with_exog.freq)

    return train_ts, test_ts


@pytest.mark.parametrize("in_column", ("target", "feat"))
def test_init(in_column):
    transform = ModelDecomposeTransform(model=HoltWintersModel(), in_column=in_column)
    assert transform.required_features == [in_column]
    assert transform._first_timestamp is None
    assert transform._last_timestamp is None


def test_usupported_model():
    with pytest.raises(ValueError, match=".* is not supported! Supported models are:"):
        ModelDecomposeTransform(model=CatBoostPerSegmentModel())


def test_prepare_ts_invalid_feature(simple_tsdf):
    transform = ModelDecomposeTransform(model=HoltWintersModel(), in_column="feat")
    with pytest.raises(KeyError, match="feat"):
        _ = transform._prepare_ts(ts=simple_tsdf)


def test_is_not_fitted(simple_tsdf):
    transform = ModelDecomposeTransform(model=HoltWintersModel(), in_column="feat")
    with pytest.raises(ValueError, match="Transform is not fitted!"):
        transform.transform(ts=simple_tsdf)


def test_prepare_ts_in_column_target(ts_with_exog):
    ts = ts_with_exog

    transform = ModelDecomposeTransform(model=HoltWintersModel(), in_column="target")
    prepared_ts = transform._prepare_ts(ts=ts)

    assert prepared_ts is not ts
    assert prepared_ts.df_exog is None
    pd.testing.assert_frame_equal(prepared_ts.df, ts[..., "target"])


@pytest.mark.parametrize(
    "ts_name,in_column",
    (
        ("outliers_df_with_two_columns", "feature"),
        ("ts_with_exog", "exog"),
        ("ts_with_exog", "holiday"),
    ),
)
def test_prepare_ts_in_column_feature(ts_name, in_column, request):
    ts = request.getfixturevalue(ts_name)

    transform = ModelDecomposeTransform(model=HoltWintersModel(), in_column=in_column)
    prepared_ts = transform._prepare_ts(ts=ts)

    assert prepared_ts is not ts
    assert "feature" not in prepared_ts.features
    assert prepared_ts.df_exog is None
    pd.testing.assert_frame_equal(
        prepared_ts.df, ts[..., in_column].rename({in_column: "target"}, axis=1, level="feature")
    )


@pytest.mark.parametrize(
    "ts_name,in_column",
    (
        ("outliers_df_with_two_columns", "target"),
        ("outliers_df_with_two_columns", "feature"),
        ("ts_with_exog", "target"),
        ("ts_with_exog", "exog"),
        ("ts_with_exog", "holiday"),
        ("example_tsds_int_timestamp", "target"),
    ),
)
def test_fit(ts_name, in_column, request):
    ts = request.getfixturevalue(ts_name)
    transform = ModelDecomposeTransform(model=HoltWintersModel(), in_column=in_column)
    transform.fit(ts=ts)

    assert transform._first_timestamp == ts.index.min()
    assert transform._last_timestamp == ts.index.max()


@pytest.mark.parametrize("residuals", (True, False))
@pytest.mark.parametrize("in_column", ("target", "exog"))
def test_add_residulas(ts_with_exog, residuals, in_column):
    ts = ts_with_exog

    transform = ModelDecomposeTransform(model=HoltWintersModel(), in_column=in_column, residuals=residuals)
    transformed = transform.fit_transform(ts=ts)

    assert (f"{in_column}_residuals" in transformed.features) is residuals


def test_timestamp_from_future(ts_with_exog_train_test):
    train, test = ts_with_exog_train_test
    transform = ModelDecomposeTransform(model=HoltWintersModel())
    transform.fit_transform(train)

    with pytest.raises(ValueError, match="Dataset to be transformed must contain historical observations in range"):
        transform.transform(test)


def test_timestamp_from_history(ts_with_exog_train_test):
    test, train = ts_with_exog_train_test
    transform = ModelDecomposeTransform(model=HoltWintersModel())
    transform.fit_transform(train)

    with pytest.raises(ValueError, match="First index of the dataset to be transformed must be larger"):
        transform.transform(test)


@pytest.mark.parametrize(
    "in_column",
    (
        "target",
        "holiday",
        "exog",
    ),
)
@pytest.mark.parametrize("horizon", (1, 5))
def test_simple_pipeline_forecast(ts_with_exog, in_column, horizon):
    ts = ts_with_exog

    pipeline = simple_pipeline_with_decompose(in_column=in_column, horizon=horizon)

    pipeline.fit(ts=ts)
    forecast = pipeline.forecast()

    assert forecast.size()[0] == horizon
    assert np.sum(forecast[..., "target"].isna().sum()) == 0


@pytest.mark.parametrize(
    "in_column",
    (
        "target",
        "holiday",
        "exog",
    ),
)
@pytest.mark.parametrize("horizon", (1, 5))
def test_simple_pipeline_predict(ts_with_exog, in_column, horizon):
    ts = ts_with_exog

    pipeline = simple_pipeline_with_decompose(in_column=in_column, horizon=horizon)

    pipeline.fit(ts=ts)
    forecast = pipeline.predict(ts)

    assert forecast.size()[0] == ts.size()[0]
    assert np.sum(forecast[..., "target"].isna().sum()) == 0


@pytest.mark.parametrize(
    "in_column",
    (
        "target",
        "holiday",
        "exog",
    ),
)
@pytest.mark.parametrize("horizon", (1, 5))
def test_simple_pipeline_predict_components(ts_with_exog, in_column, horizon):
    ts = ts_with_exog

    pipeline = simple_pipeline_with_decompose(in_column=in_column, horizon=horizon)

    pipeline.fit(ts=ts)
    forecast = pipeline.predict(ts, return_components=True)

    assert forecast.size()[0] == ts.size()[0]
    assert forecast.target_components_names == ("target_component_level",)


@pytest.mark.parametrize(
    "in_column",
    (
        "target",
        "holiday",
        "exog",
    ),
)
@pytest.mark.parametrize("horizon", (1, 5))
def test_simple_pipeline_backtest(ts_with_exog, in_column, horizon):
    ts = ts_with_exog

    pipeline = simple_pipeline_with_decompose(in_column=in_column, horizon=horizon)

    _, forecast, _ = pipeline.backtest(ts=ts, metrics=[MAE()], n_folds=3)

    assert len(forecast) == horizon * 3
    assert np.sum(forecast.loc[:, pd.IndexSlice[:, "target"]].isna().sum()) == 0


@pytest.mark.parametrize(
    "ts_name,in_column",
    (
        ("outliers_df_with_two_columns", "target"),
        ("outliers_df_with_two_columns", "feature"),
        ("ts_with_exog", "target"),
        ("ts_with_exog", "exog"),
    ),
)
@pytest.mark.parametrize(
    "decompose_model",
    (
        HoltWintersModel(),
        ProphetModel(),
    ),
)
@pytest.mark.parametrize("forecast_model", (HoltWintersModel(), ProphetModel(), CatBoostPerSegmentModel(iterations=10)))
def test_pipeline_models(ts_name, in_column, decompose_model, forecast_model, request):
    ts = request.getfixturevalue(ts_name)

    pipeline = Pipeline(
        transforms=[ModelDecomposeTransform(model=decompose_model, in_column=in_column)],
        model=forecast_model,
        horizon=3,
    )

    pipeline.fit(ts)
    forecast = pipeline.forecast()

    assert forecast.size()[0] == 3
    assert np.sum(forecast.loc[:, pd.IndexSlice[:, "target"]].isna().sum()) == 0


@pytest.mark.parametrize(
    "decompose_model",
    (
        HoltWintersModel(),
        ProphetModel(),
        SARIMAXModel(),
        DeadlineMovingAverageModel(),
        SeasonalMovingAverageModel(),
        BATSModel(use_arma_errors=False),
        TBATSModel(use_arma_errors=False),
    ),
)
def test_decompose_models(ts_with_exog, decompose_model):
    pipeline = Pipeline(
        transforms=[ModelDecomposeTransform(model=decompose_model, in_column="exog")],
        model=CatBoostPerSegmentModel(iterations=10),
        horizon=3,
    )

    pipeline.fit(ts_with_exog)
    forecast = pipeline.forecast()

    assert forecast.size()[0] == 3
    assert np.sum(forecast.loc[:, pd.IndexSlice[:, "target"]].isna().sum()) == 0


@pytest.mark.parametrize("answer", ({"1": ["2021-01-11"], "2": ["2021-01-27"]},))
def test_outlier_detection(outliers_solid_tsds, answer):
    ts = outliers_solid_tsds

    transforms = [
        ModelDecomposeTransform(
            model=HoltWintersModel(seasonal="add", seasonal_periods=3), in_column="target", residuals=True
        ),
        IForestOutlierTransform(
            in_column="target",
            features_to_use=["target_residuals", "target_seasonality", "target_level"],
            contamination=0.01,
        ),
    ]
    ts.fit_transform(transforms)

    for segment in ts.segments:
        empty_values = pd.isna(ts[:, segment, "target"])
        assert empty_values.sum() == len(answer[segment])
        assert all(empty_values[answer[segment]])


def test_outlier_detection_pipeline(outliers_solid_tsds):
    ts = outliers_solid_tsds
    pipeline = Pipeline(
        transforms=[
            ModelDecomposeTransform(model=HoltWintersModel(), in_column="target"),
            IForestOutlierTransform(in_column="target"),
            TimeSeriesImputerTransform(in_column="target"),
        ],
        model=SARIMAXModel(),
        horizon=3,
    )
    pipeline.fit(ts)


@pytest.mark.parametrize(
    "decompose_model, context_size",
    (
        (HoltWintersModel(), 0),
        (ProphetModel(), 0),
        (SARIMAXModel(), 0),
        (SeasonalMovingAverageModel(window=3, seasonality=1), 3),
        (BATSModel(use_arma_errors=False, use_trend=True), 0),
        (TBATSModel(use_arma_errors=False, use_trend=True), 0),
    ),
)
def test_stride_transform(forward_stride_datasets, decompose_model, context_size):
    train, test = forward_stride_datasets

    transform = ModelDecomposeTransform(model=decompose_model, residuals=True)

    transform.fit(train)
    transformed = transform.transform(test)

    assert not transformed.df.iloc[context_size:10].isna().any().any()
    assert transformed.df.iloc[10:].isna().all().any()
