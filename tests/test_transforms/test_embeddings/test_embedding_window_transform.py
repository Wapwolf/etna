import pathlib
from copy import deepcopy
from unittest.mock import Mock

import pandas as pd
import pytest

from etna.datasets import TSDataset
from etna.metrics import SMAPE
from etna.models import LinearMultiSegmentModel
from etna.pipeline import Pipeline
from etna.transforms import EmbeddingWindowTransform
from etna.transforms import FilterFeaturesTransform
from etna.transforms import LagTransform
from etna.transforms.embeddings.models import TS2VecEmbeddingModel


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=3, n_epochs=1),
    ],
)
@pytest.mark.smoke
def test_fit(ts_with_exog_nan_begin, embedding_model):
    transform = EmbeddingWindowTransform(
        in_columns=["target", "exog_1", "exog_2"], embedding_model=embedding_model, out_column="emb"
    )
    transform.fit(ts=ts_with_exog_nan_begin)


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=3, n_epochs=1),
    ],
)
@pytest.mark.smoke
def test_fit_transform(ts_with_exog_nan_begin, embedding_model):
    transform = EmbeddingWindowTransform(
        in_columns=["target", "exog_1", "exog_2"], embedding_model=embedding_model, out_column="emb"
    )
    transform.fit_transform(ts=ts_with_exog_nan_begin)


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=1, n_epochs=1, output_dims=2),
    ],
)
@pytest.mark.smoke
def test_fit_forecast(example_tsds, embedding_model):
    emb_transform = EmbeddingWindowTransform(in_columns=["target"], embedding_model=embedding_model, out_column="emb")
    output_dims = embedding_model.output_dims
    lag_transforms = [LagTransform(in_column=f"emb_{i}", lags=[7], out_column=f"lag_{i}") for i in range(output_dims)]
    filter_transforms = FilterFeaturesTransform(exclude=[f"emb_{i}" for i in range(output_dims)])
    transforms = [emb_transform] + lag_transforms + [filter_transforms]

    pipeline = Pipeline(model=LinearMultiSegmentModel(), transforms=transforms, horizon=7)
    pipeline.fit(example_tsds).forecast()


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=1, n_epochs=1, output_dims=2),
    ],
)
@pytest.mark.smoke
def test_backtest(example_tsds, embedding_model):
    emb_transform = EmbeddingWindowTransform(in_columns=["target"], embedding_model=embedding_model, out_column="emb")
    output_dims = embedding_model.output_dims
    lag_transforms = [LagTransform(in_column=f"emb_{i}", lags=[7], out_column=f"lag_{i}") for i in range(output_dims)]
    filter_transforms = FilterFeaturesTransform(exclude=[f"emb_{i}" for i in range(output_dims)])
    transforms = [emb_transform] + lag_transforms + [filter_transforms]

    pipeline = Pipeline(model=LinearMultiSegmentModel(), transforms=transforms, horizon=7)
    pipeline.backtest(ts=example_tsds, metrics=[SMAPE()], n_folds=2, n_jobs=2, joblib_params=dict(backend="loky"))


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=3, n_epochs=1),
    ],
)
@pytest.mark.smoke
def test_save(ts_with_exog_nan_begin, tmp_path, embedding_model):
    transform = EmbeddingWindowTransform(
        in_columns=["target", "exog_1", "exog_2"], embedding_model=embedding_model, out_column="emb"
    )
    transform.fit(ts=ts_with_exog_nan_begin)

    path = pathlib.Path(tmp_path) / "tmp.zip"
    transform.save(path=path)


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=3, n_epochs=1),
    ],
)
@pytest.mark.smoke
def test_load(ts_with_exog_nan_begin, tmp_path, embedding_model):
    transform = EmbeddingWindowTransform(
        in_columns=["target", "exog_1", "exog_2"], embedding_model=embedding_model, out_column="emb"
    )
    transform.fit(ts=ts_with_exog_nan_begin)

    path = pathlib.Path(tmp_path) / "tmp.zip"
    transform.save(path=path)
    EmbeddingWindowTransform.load(path=path)


@pytest.mark.parametrize(
    "output_dims, out_column, expected_out_columns",
    [(2, "emb", ["emb_0", "emb_1"]), (3, "lag", ["lag_0", "lag_1", "lag_2"])],
)
def test_get_out_columns(output_dims, out_column, expected_out_columns):
    transform = EmbeddingWindowTransform(
        in_columns=Mock(), embedding_model=Mock(output_dims=output_dims), out_column=out_column
    )
    assert sorted(expected_out_columns) == sorted(transform._get_out_columns())


@pytest.mark.parametrize("embedding_model", [TS2VecEmbeddingModel(input_dims=3, n_epochs=1)])
def test_second_fit_not_update_state(ts_with_exog_nan_begin, embedding_model):
    transform = EmbeddingWindowTransform(
        in_columns=["target", "exog_1", "exog_2"], embedding_model=embedding_model, out_column="emb"
    )
    first_fit_encoded = transform.fit_transform(ts=deepcopy(ts_with_exog_nan_begin))
    second_fit_encoded = transform.fit_transform(ts=deepcopy(ts_with_exog_nan_begin))
    pd.testing.assert_frame_equal(first_fit_encoded.to_pandas(), second_fit_encoded.to_pandas())


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=3, output_dims=3, n_epochs=1),
    ],
)
def test_transform_format(
    ts_with_exog_nan_begin, embedding_model, expected_columns=("target", "exog_1", "exog_2", "emb_0", "emb_1", "emb_2")
):
    transform = EmbeddingWindowTransform(
        in_columns=["target", "exog_1", "exog_2"], embedding_model=embedding_model, out_column="emb"
    )
    transform.fit_transform(ts=ts_with_exog_nan_begin)
    obtained_columns = set(ts_with_exog_nan_begin.columns.get_level_values("feature"))
    assert sorted(obtained_columns) == sorted(expected_columns)


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=3, output_dims=3, n_epochs=1),
    ],
)
def test_transform_new_segments(
    ts_with_exog_nan_begin, embedding_model, expected_columns=("target", "exog_1", "exog_2", "emb_0", "emb_1", "emb_2")
):
    train_ts = TSDataset(df=ts_with_exog_nan_begin[:, ["segment_0"], :], freq="D")

    transform = EmbeddingWindowTransform(
        in_columns=["target", "exog_1", "exog_2"], embedding_model=embedding_model, out_column="emb"
    )
    transform.fit(ts=train_ts)
    transform.transform(ts=ts_with_exog_nan_begin)

    obtained_columns = set(ts_with_exog_nan_begin.columns.get_level_values("feature"))
    assert sorted(obtained_columns) == sorted(expected_columns)


@pytest.mark.parametrize(
    "embedding_model",
    [
        TS2VecEmbeddingModel(input_dims=3, output_dims=3, n_epochs=1),
    ],
)
def test_transform_load_pre_fitted(ts_with_exog_nan_begin, tmp_path, embedding_model):
    transform = EmbeddingWindowTransform(
        in_columns=["target", "exog_1", "exog_2"], embedding_model=embedding_model, out_column="emb"
    )
    before_load_ts = transform.fit_transform(ts=deepcopy(ts_with_exog_nan_begin))

    path = pathlib.Path(tmp_path) / "tmp.zip"
    transform.save(path=path)

    loaded_transform = EmbeddingWindowTransform.load(path=path)
    after_load_ts = loaded_transform.transform(ts=deepcopy(ts_with_exog_nan_begin))

    pd.testing.assert_frame_equal(before_load_ts.to_pandas(), after_load_ts.to_pandas())
