from collections.abc import Callable
from unittest.mock import Mock, MagicMock, call

import pytest
import torch
from pytest_mock import MockerFixture

from country_workspace.contrib.name_parser.parser import LSTM


@pytest.fixture
def embedding_mock(mocker: MockerFixture) -> torch.nn.Embedding:
    return mocker.patch("country_workspace.contrib.name_parser.parser.nn.Embedding")


@pytest.fixture
def lstm_mock(mocker: MockerFixture) -> torch.nn.LSTM:
    return mocker.patch("country_workspace.contrib.name_parser.parser.nn.LSTM")


@pytest.fixture
def linear_mock(mocker: MockerFixture) -> torch.nn.Linear:
    return mocker.patch("country_workspace.contrib.name_parser.parser.nn.Linear")


@pytest.fixture
def log_softmax_mock(mocker: MockerFixture) -> torch.nn.LogSoftmax:
    return mocker.patch("country_workspace.contrib.name_parser.parser.nn.LogSoftmax")


@pytest.fixture
def zeros_mock(mocker: MockerFixture) -> torch.Tensor:
    return mocker.patch("country_workspace.contrib.name_parser.parser.torch.zeros")


def test_lstm_class_init(
    embedding_mock: torch.nn.Embedding,
    lstm_mock: torch.nn.LSTM,
    linear_mock: torch.nn.Linear,
    log_softmax_mock: torch.nn.LogSoftmax,
) -> None:
    instance = Mock(spec=LSTM)
    input_size, hidden_size, output_size, num_layers = range(4)

    LSTM.__init__(instance, input_size, hidden_size, output_size, num_layers)

    assert instance.hidden_size == hidden_size
    assert instance.num_layers == num_layers
    assert instance.embedding == embedding_mock.return_value
    assert instance.lstm == lstm_mock.return_value
    assert instance.fc == linear_mock.return_value
    assert instance.softmax == log_softmax_mock.return_value

    embedding_mock.assert_called_with(input_size, hidden_size)
    lstm_mock.assert_called_once_with(hidden_size, hidden_size, num_layers, batch_first=True)
    linear_mock.assert_called_once_with(hidden_size, output_size)
    log_softmax_mock.assert_called_once_with(dim=1)


def test_lstm_class_forward(
    embedding_mock: torch.nn.Embedding,
    lstm_mock: torch.nn.LSTM,
    linear_mock: torch.nn.Linear,
    log_softmax_mock: torch.nn.LogSoftmax,
    zeros_mock: Callable,
) -> None:
    instance = Mock(spec=LSTM)
    input_ = Mock(spec=torch.Tensor)
    input_size, hidden_size, output_size, num_layers = range(4)
    lstm_mock.return_value.return_value = (lstm_out := MagicMock()), None
    LSTM.__init__(instance, input_size, hidden_size, output_size, num_layers)

    assert LSTM.forward(instance, input_) == instance.softmax.return_value

    input_.type.assert_called_with(torch.IntTensor)
    input_.type.return_value.to.assert_called_with(input_.device)
    instance.embedding.assert_called_once_with(input_.type.return_value.to.return_value)
    instance.embedding.return_value.size.assert_has_calls(
        [
            c := call(0),
            c,
        ]
    )
    zeros_mock.assert_has_calls(
        [
            c0 := call(num_layers, instance.embedding.return_value.size.return_value, hidden_size),
            c1 := call().to(input_.device),
            c0,
            c1,
        ]
    )
    instance.lstm.assert_called_once_with(
        instance.embedding.return_value, (zt := zeros_mock.return_value.to.return_value, zt)
    )
    lstm_out.__getitem__.assert_called_once_with((slice(None), -1, slice(None)))
    instance.fc.assert_called_once_with(lstm_out.__getitem__.return_value)
    instance.softmax.assert_called_once_with(instance.fc.return_value)
