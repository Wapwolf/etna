import pathlib
import tempfile
import zipfile
from copy import deepcopy
from typing import List
from typing import Optional
from typing import Union

import pandas as pd
from typing_extensions import Self

from etna.core import SaveMixin
from etna.core import load
from etna.datasets import TSDataset
from etna.loggers import tslogger
from etna.pipeline.base import BasePipeline


class EnsembleMixin:
    """Base mixin for the ensembles."""

    @staticmethod
    def _validate_pipeline_number(pipelines: List[BasePipeline]):
        """Check that given valid number of pipelines."""
        if len(pipelines) < 2:
            raise ValueError("At least two pipelines are expected.")

    @staticmethod
    def _get_horizon(pipelines: List[BasePipeline]) -> int:
        """Get ensemble's horizon."""
        horizons = {pipeline.horizon for pipeline in pipelines}
        if len(horizons) > 1:
            raise ValueError("All the pipelines should have the same horizon.")
        return horizons.pop()

    @staticmethod
    def _fit_pipeline(pipeline: BasePipeline, ts: TSDataset) -> BasePipeline:
        """Fit given pipeline with ``ts``."""
        tslogger.log(msg=f"Start fitting {pipeline}.")
        pipeline.fit(ts=ts, save_ts=False)
        tslogger.log(msg=f"Pipeline {pipeline} is fitted.")
        return pipeline

    @staticmethod
    def _forecast_pipeline(pipeline: BasePipeline, ts: TSDataset) -> TSDataset:
        """Make forecast with given pipeline."""
        tslogger.log(msg=f"Start forecasting with {pipeline}.")
        forecast = pipeline.forecast(ts=ts)
        tslogger.log(msg=f"Forecast is done with {pipeline}.")
        return forecast

    @staticmethod
    def _predict_pipeline(
        ts: TSDataset,
        pipeline: BasePipeline,
        start_timestamp: Union[pd.Timestamp, int, str, None],
        end_timestamp: Union[pd.Timestamp, int, str, None],
    ) -> TSDataset:
        """Make predict with given pipeline."""
        tslogger.log(msg=f"Start prediction with {pipeline}.")
        prediction = pipeline.predict(ts=ts, start_timestamp=start_timestamp, end_timestamp=end_timestamp)
        tslogger.log(msg=f"Prediction is done with {pipeline}.")
        return prediction


class SaveEnsembleMixin(SaveMixin):
    """Implementation of ``AbstractSaveable`` abstract class for ensemble pipelines.

    It saves object to the zip archive with 3 entities:

    * metadata.json: contains library version and class name.

    * object.pkl: pickled without pipelines and ts.

    * pipelines: folder with saved pipelines.
    """

    def save(self, path: pathlib.Path):
        """Save the object.

        Parameters
        ----------
        path:
            Path to save object to.
        """
        self.pipelines: List[BasePipeline]
        self.ts: Optional[TSDataset]

        self._save(path=path, skip_attributes=["pipelines", "ts"])

        with zipfile.ZipFile(path, "a") as archive:
            with tempfile.TemporaryDirectory() as _temp_dir:
                temp_dir = pathlib.Path(_temp_dir)

                # save transforms separately
                pipelines_dir = temp_dir / "pipelines"
                pipelines_dir.mkdir()
                num_digits = 8
                for i, pipeline in enumerate(self.pipelines):
                    save_name = f"{i:0{num_digits}d}.zip"
                    pipeline_save_path = pipelines_dir / save_name
                    pipeline.save(pipeline_save_path)
                    archive.write(pipeline_save_path, f"pipelines/{save_name}")

    @classmethod
    def load(cls, path: pathlib.Path, ts: Optional[TSDataset] = None) -> Self:
        """Load an object.

        Warning
        -------
        This method uses :py:mod:`dill` module which is not secure.
        It is possible to construct malicious data which will execute arbitrary code during loading.
        Never load data that could have come from an untrusted source, or that could have been tampered with.

        Parameters
        ----------
        path:
            Path to load object from.
        ts:
            TSDataset to set into loaded pipeline.

        Returns
        -------
        :
            Loaded object.
        """
        obj = super().load(path=path)
        obj.ts = deepcopy(ts)

        with zipfile.ZipFile(path, "r") as archive:
            with tempfile.TemporaryDirectory() as _temp_dir:
                temp_dir = pathlib.Path(_temp_dir)

                archive.extractall(temp_dir)

                # load pipelines
                pipelines_dir = temp_dir / "pipelines"
                pipelines = []
                for path in sorted(pipelines_dir.iterdir()):
                    pipelines.append(load(path, ts=ts))

                obj.pipelines = pipelines

        return obj
