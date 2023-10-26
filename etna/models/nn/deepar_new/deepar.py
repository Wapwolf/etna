from typing import Any
from typing import Dict
from typing import Iterator
from typing import Optional
from typing import Union

import numpy as np
import pandas as pd
from typing_extensions import TypedDict

from etna import SETTINGS
from etna.distributions import BaseDistribution
from etna.distributions import FloatDistribution
from etna.distributions import IntDistribution

if SETTINGS.torch_required:
    import torch
    import torch.nn as nn
    from torch.utils.data.sampler import RandomSampler

    from etna.models.base import DeepBaseModel
    from etna.models.base import DeepBaseNet
    from etna.models.nn.deepar_new.loss import GaussianLoss
    from etna.models.nn.deepar_new.loss import NegativeBinomialLoss
    from etna.models.nn.deepar_new.sampler import SamplerWrapper


class DeepARBatchNew(TypedDict):
    """Batch specification for DeepAR."""

    encoder_real: "torch.Tensor"
    decoder_real: "torch.Tensor"
    encoder_target: "torch.Tensor"
    decoder_target: "torch.Tensor"
    segment: "torch.Tensor"
    weight: "torch.Tensor"


class DeepARNetNew(DeepBaseNet):
    """DeepAR based Lightning module with LSTM cell."""

    def __init__(
        self,
        input_size: int,
        num_layers: int,
        hidden_size: int,
        lr: float,
        scale: bool,
        n_samples: Optional[int],  # TODO
        loss: Union[GaussianLoss, NegativeBinomialLoss],
        optimizer_params: Optional[dict],
    ) -> None:
        """Init DeepAR.

        Parameters
        ----------
        input_size:
            size of the input feature space: target plus extra features
        num_layers:
            number of layers
        hidden_size:
            size of the hidden state
        lr:
            learning rate
        optimizer_params:
            parameters for optimizer for Adam optimizer (api reference :py:class:`torch.optim.Adam`)
        """
        super().__init__()
        self.save_hyperparameters()
        self.num_layers = num_layers
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.rnn = nn.LSTM(
            num_layers=self.num_layers, hidden_size=self.hidden_size, input_size=self.input_size, batch_first=True
        )
        self.linear_1 = nn.Linear(in_features=self.hidden_size, out_features=1)
        self.linear_2 = nn.Linear(in_features=self.hidden_size, out_features=1)
        self.lr = lr
        self.scale = scale
        self.n_samples = n_samples
        self.optimizer_params = {} if optimizer_params is None else optimizer_params
        self.loss = loss

    def forward(self, x: DeepARBatchNew, *args, **kwargs):  # type: ignore
        """Forward pass.

        Parameters
        ----------
        x:
            batch of data

        Returns
        -------
        :
            forecast with shape (batch_size, decoder_length, 1)
        """
        encoder_real = x["encoder_real"].float()  # (batch_size, encoder_length-1, input_size)
        decoder_real = x["decoder_real"].float()  # (batch_size, decoder_length, input_size)
        decoder_target = x["decoder_target"].float()  # (batch_size, decoder_length, 1)
        decoder_length = decoder_real.shape[1]
        weights = x["weight"]
        _, (h_n, c_n) = self.rnn(encoder_real)
        forecast = torch.zeros_like(decoder_target)  # (batch_size, decoder_length, 1)

        for i in range(decoder_length - 1):
            output, (h_n, c_n) = self.rnn(decoder_real[:, i, None], (h_n, c_n))
            loc, scale = self.get_distribution_params(output[:, -1])
            forecast_point = self.loss.sample(loc, scale, weights).flatten()
            forecast[:, i, 0] = forecast_point
            decoder_real[:, i + 1, 0] = forecast_point  # TODO можно через if

        # Last point is computed out of the loop because `decoder_real[:, i + 1, 0]` would cause index error
        output, (_, _) = self.rnn(decoder_real[:, decoder_length - 1, None], (h_n, c_n))
        loc, scale = self.get_distribution_params(output[:, -1])
        forecast_point = self.loss.sample(loc, scale, weights).flatten()
        forecast[:, decoder_length - 1, 0] = forecast_point
        return forecast

    def get_distribution_params(self, output):
        loc = self.linear_1(output) if isinstance(self.loss, GaussianLoss) else nn.Softplus()(self.linear_1(output))
        scale = nn.Softplus()(self.linear_2(output))
        return loc, scale

    def step(self, batch: DeepARBatchNew, *args, **kwargs):  # type: ignore
        """Step for loss computation for training or validation.

        Parameters
        ----------
        batch:
            batch of data

        Returns
        -------
        :
            loss, true_target, prediction_target
        """
        encoder_real = batch["encoder_real"].float()  # (batch_size, encoder_length-1, input_size)
        decoder_real = batch["decoder_real"].float()  # (batch_size, decoder_length, input_size)

        encoder_target = batch["encoder_target"].float()  # (batch_size, encoder_length-1, 1)
        decoder_target = batch["decoder_target"].float()  # (batch_size, decoder_length, 1)
        weights = batch["weight"]
        target = torch.cat((encoder_target, decoder_target), dim=1)

        output, (_, _) = self.rnn(torch.cat((encoder_real, decoder_real), dim=1))
        loc, scale = self.get_distribution_params(output)
        target_prediction = self.loss.sample(loc, scale, weights)
        loss = self.loss(target, loc, scale, weights)
        return loss, target, target_prediction

    def make_samples(self, df: pd.DataFrame, encoder_length: int, decoder_length: int) -> Iterator[dict]:
        """Make samples from segment DataFrame."""
        segment = df["segment"].values[0]
        values_target = df["target"].values
        values_real = (
            df.select_dtypes(include=[np.number])
            .assign(target_shifted=df["target"].shift(1))
            .drop(["target"], axis=1)
            .pipe(lambda x: x[["target_shifted"] + [i for i in x.columns if i != "target_shifted"]])
            .values
        )

        def _make(
            values_real: np.ndarray,
            values_target: np.ndarray,
            segment: str,
            start_idx: int,
            encoder_length: int,
            decoder_length: int,
        ) -> Optional[dict]:

            sample: Dict[str, Any] = {
                "encoder_real": list(),
                "decoder_real": list(),
                "encoder_target": list(),
                "decoder_target": list(),
                "segment": None,
                "weight": None,
            }
            total_length = len(values_target)
            total_sample_length = encoder_length + decoder_length

            if total_sample_length + start_idx > total_length:
                return None
            # if start_idx < 0:
            #     sample["decoder_real"] = values_real[start_idx + encoder_length : start_idx + total_sample_length]
            #
            #     # Get shifted target and concatenate it with real values features
            #     sample["encoder_real"] = values_real[: start_idx + encoder_length]
            #     sample["encoder_real"] = sample["encoder_real"][1:]
            #
            #     target = values_target[: start_idx + total_sample_length].reshape(-1, 1)
            #     sample["encoder_target"] = target[1 : start_idx + encoder_length]
            #     sample["decoder_target"] = target[start_idx + encoder_length :]
            #
            #     sample["encoder_real"] = np.pad(
            #         sample["encoder_real"], ((-start_idx, 0), (0, 0)), "constant", constant_values=0
            #     )
            #     sample["encoder_target"] = np.pad(
            #         sample["encoder_target"], ((-start_idx, 0), (0, 0)), "constant", constant_values=0
            #     )

            # Get shifted target and concatenate it with real values features
            sample["decoder_real"] = values_real[start_idx + encoder_length : start_idx + total_sample_length]

            # Get shifted target and concatenate it with real values features
            sample["encoder_real"] = values_real[start_idx : start_idx + encoder_length]
            sample["encoder_real"] = sample["encoder_real"][1:]

            target = values_target[start_idx : start_idx + total_sample_length].reshape(-1, 1)
            sample["encoder_target"] = target[1:encoder_length]
            sample["decoder_target"] = target[encoder_length:]

            sample["segment"] = segment

            if self.scale:
                sample["weight"] = 1 + sample["encoder_real"].mean()
                sample["encoder_real"] = sample["encoder_real"] / sample["weight"]
                sample["decoder_real"] = sample["decoder_real"] / sample["weight"]
                sample["encoder_target"] = sample["encoder_target"] / sample["weight"]
                sample["decoder_target"] = sample["decoder_target"] / sample["weight"]
            else:
                sample["weight"] = float("nan")

            return sample

        # start_idx = -(encoder_length - 2)  # TODO is good?
        start_idx = 0
        while True:
            batch = _make(
                values_target=values_target,
                values_real=values_real,
                segment=segment,
                start_idx=start_idx,
                encoder_length=encoder_length,
                decoder_length=decoder_length,
            )
            if batch is None:
                break
            yield batch
            start_idx += 1

    def configure_optimizers(self) -> "torch.optim.Optimizer":
        """Optimizer configuration."""
        optimizer = torch.optim.Adam(self.parameters(), lr=self.lr, **self.optimizer_params)
        return optimizer


class DeepARModelNew(DeepBaseModel):
    """DeepAR based model on LSTM cell.

    Note
    ----
    This model requires ``torch`` extension to be installed.
    Read more about this at :ref:`installation page <installation>`.
    """

    def __init__(
        self,
        input_size: int,
        decoder_length: int,
        encoder_length: int,
        num_layers: int = 2,
        hidden_size: int = 16,
        lr: float = 1e-3,
        scale: bool = True,
        n_samples: Optional[int] = None,
        loss: Optional["torch.nn.Module"] = None,
        train_batch_size: int = 16,
        test_batch_size: int = 16,
        optimizer_params: Optional[dict] = None,
        trainer_params: Optional[dict] = None,
        train_dataloader_params: Optional[dict] = None,
        test_dataloader_params: Optional[dict] = None,
        val_dataloader_params: Optional[dict] = None,
        split_params: Optional[dict] = None,
        sampler: Optional[str] = None,
    ):
        """Init RNN model based on LSTM cell.

        Parameters
        ----------
        input_size:
            size of the input feature space: target plus extra features
        encoder_length:
            encoder length
        decoder_length:
            decoder length
        num_layers:
            number of layers
        hidden_size:
            size of the hidden state
        lr:
            learning rate
        train_batch_size:
            batch size for training
        test_batch_size:
            batch size for testing
        optimizer_params:
            parameters for optimizer for Adam optimizer (api reference :py:class:`torch.optim.Adam`)
        trainer_params:
            Pytorch ligthning  trainer parameters (api reference :py:class:`pytorch_lightning.trainer.trainer.Trainer`)
        train_dataloader_params:
            parameters for train dataloader like sampler for example (api reference :py:class:`torch.utils.data.DataLoader`)
        test_dataloader_params:
            parameters for test dataloader
        val_dataloader_params:
            parameters for validation dataloader
        split_params:
            dictionary with parameters for :py:func:`torch.utils.data.random_split` for train-test splitting
                * **train_size**: (*float*) value from 0 to 1 - fraction of samples to use for training

                * **generator**: (*Optional[torch.Generator]*) - generator for reproducibile train-test splitting

                * **torch_dataset_size**: (*Optional[int]*) - number of samples in dataset, in case of dataset not implementing ``__len__``
        """
        self.input_size = input_size
        self.num_layers = num_layers
        self.hidden_size = hidden_size
        self.lr = lr
        self.scale = scale
        self.n_samples = n_samples
        self.optimizer_params = optimizer_params
        self.loss = loss
        self.train_dataloader_params = train_dataloader_params
        self.val_dataloader_params = val_dataloader_params
        self.test_dataloader_params = test_dataloader_params
        super().__init__(
            net=DeepARNetNew(
                input_size=input_size,
                num_layers=num_layers,
                hidden_size=hidden_size,
                lr=lr,
                scale=scale,
                n_samples=n_samples,
                optimizer_params=optimizer_params,
                loss=GaussianLoss() if loss is None else loss,
            ),
            decoder_length=decoder_length,
            encoder_length=encoder_length,
            train_batch_size=train_batch_size,
            test_batch_size=test_batch_size,
            train_dataloader_params=train_dataloader_params
            if train_dataloader_params is not None
            else {"sampler": SamplerWrapper(RandomSampler)},
            test_dataloader_params=val_dataloader_params if val_dataloader_params is not None else {},
            val_dataloader_params=test_dataloader_params if test_dataloader_params is not None else {},
            trainer_params=trainer_params,
            split_params=split_params,
        )

    def params_to_tune(self) -> Dict[str, BaseDistribution]:
        """Get default grid for tuning hyperparameters.

        This grid tunes parameters: ``num_layers``, ``hidden_size``, ``lr``, ``encoder_length``.
        Other parameters are expected to be set by the user.

        Returns
        -------
        :
            Grid to tune.
        """
        return {
            "num_layers": IntDistribution(low=1, high=3),
            "hidden_size": IntDistribution(low=4, high=64, step=4),
            "lr": FloatDistribution(low=1e-5, high=1e-2, log=True),
            "encoder_length": IntDistribution(low=1, high=20),
        }