from typing import TYPE_CHECKING
from typing import Callable
from typing import Dict
from typing import List

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from etna.datasets import TSDataset


def absolute_difference_distance(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Calculate distance for :py:func:`get_anomalies_density` function by taking absolute value of difference.

    Parameters
    ----------
    x:
        first value
    y:
        second value

    Returns
    -------
    result: float
        absolute difference between values
    """
    return np.abs(x - y)


def get_segment_density_outliers_indices(
    series: np.ndarray,
    window_size: int = 7,
    distance_threshold: float = 10,
    n_neighbors: int = 3,
    distance_func: Callable[[np.ndarray, np.ndarray], np.ndarray] = absolute_difference_distance,
) -> List[int]:
    """Get indices of outliers for one series.

    Parameters
    ----------
    series:
        array to find outliers in
    window_size:
        size of window
    distance_threshold:
        if distance between two items in the window is less than threshold those items are supposed to be close to each other
    n_neighbors:
        min number of close items that item should have not to be outlier
    distance_func:
        distance function

    Returns
    -------
    :
        list of outliers' indices
    """

    def is_close(item1: np.ndarray, item2: np.ndarray) -> np.ndarray:
        """Return 1 if item1 is closer to item2 than distance_threshold according to distance_func, 0 otherwise."""
        return distance_func(item1, item2) < distance_threshold

    idxs = np.arange(len(series))
    start_idxs = np.maximum(0, idxs - window_size)
    end_idxs = np.maximum(0, np.minimum(idxs, len(series) - window_size)) + 1

    deltas: np.ndarray = end_idxs - start_idxs

    outliers_indices = []
    for idx, item, start_idx, delta in zip(idxs, series, start_idxs, deltas):
        closeness = is_close(series[start_idx : start_idx + window_size + delta - 1], item)

        num_close = np.cumsum(closeness)

        outlier = True
        for d in range(delta):
            est_neighbors = num_close[-delta + d] - num_close[d]
            if (start_idx + d) != idx:
                est_neighbors += closeness[d] - 1

            if est_neighbors >= n_neighbors:
                outlier = False
                break

        if outlier:
            outliers_indices.append(idx)

    return outliers_indices


def get_anomalies_density(
    ts: "TSDataset",
    in_column: str = "target",
    window_size: int = 15,
    distance_coef: float = 3,
    n_neighbors: int = 3,
    distance_func: Callable[[np.ndarray, np.ndarray], np.ndarray] = absolute_difference_distance,
) -> Dict[str, List[pd.Timestamp]]:
    """Compute outliers according to density rule.

    For each element in the series build all the windows of size ``window_size`` containing this point.
    If any of the windows contains at least ``n_neighbors`` that are closer than ``distance_coef * std(series)``
    to target point according to ``distance_func`` target point is not an outlier.

    Parameters
    ----------
    ts:
        TSDataset with timeseries data
    in_column:
        name of the column in which the anomaly is searching
    window_size:
        size of windows to build
    distance_coef:
        factor for standard deviation that forms distance threshold to determine points are close to each other
    n_neighbors:
        min number of close neighbors of point not to be outlier
    distance_func:
        distance function

    Returns
    -------
    :
        dict of outliers in format {segment: [outliers_timestamps]}

    Notes
    -----
    It is a variation of distance-based (index) outlier detection method adopted for timeseries.
    """
    segments = ts.segments
    outliers_per_segment = {}
    for seg in segments:
        # TODO: dropna() now is responsible for removing nan-s at the end of the sequence and in the middle of it
        #   May be error or warning should be raised in this case
        segment_df = ts[:, seg, in_column].dropna()
        series = segment_df.values
        timestamps = segment_df.index.values
        series_std = np.std(series)
        if series_std:
            outliers_idxs = get_segment_density_outliers_indices(
                series=series,
                window_size=window_size,
                distance_threshold=distance_coef * series_std,
                n_neighbors=n_neighbors,
                distance_func=distance_func,
            )

            if len(outliers_idxs):
                outliers_per_segment[seg] = list(timestamps[outliers_idxs])

    return outliers_per_segment


__all__ = ["get_anomalies_density", "absolute_difference_distance"]
