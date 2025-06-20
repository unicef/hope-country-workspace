from unittest.mock import Mock, MagicMock, call

import pytest
import torch
from pytest_mock import MockerFixture

from country_workspace.contrib.name_parser.parser import (
    LSTM,
    read_config,
    load_model,
    get_line_to_tensor_converter,
    get_parser,
    BASE_PATH,
    MODEL_PATH_TEMPLATE,
)


@pytest.fixture
def nn_embedding_mock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("country_workspace.contrib.name_parser.parser.nn.Embedding")


@pytest.fixture
def nn_lstm_mock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("country_workspace.contrib.name_parser.parser.nn.LSTM")


@pytest.fixture
def nn_linear_mock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("country_workspace.contrib.name_parser.parser.nn.Linear")


@pytest.fixture
def nn_log_softmax_mock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("country_workspace.contrib.name_parser.parser.nn.LogSoftmax")


@pytest.fixture
def torch_zeros_mock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("country_workspace.contrib.name_parser.parser.torch.zeros")


def test_lstm_class_init(
    nn_embedding_mock: MagicMock,
    nn_lstm_mock: MagicMock,
    nn_linear_mock: MagicMock,
    nn_log_softmax_mock: MagicMock,
) -> None:
    instance = Mock(spec=LSTM)
    input_size, hidden_size, output_size, num_layers = range(4)

    LSTM.__init__(instance, input_size, hidden_size, output_size, num_layers)

    assert instance.hidden_size == hidden_size
    assert instance.num_layers == num_layers
    assert instance.embedding == nn_embedding_mock.return_value
    assert instance.lstm == nn_lstm_mock.return_value
    assert instance.fc == nn_linear_mock.return_value
    assert instance.softmax == nn_log_softmax_mock.return_value

    nn_embedding_mock.assert_called_with(input_size, hidden_size)
    nn_lstm_mock.assert_called_once_with(hidden_size, hidden_size, num_layers, batch_first=True)
    nn_linear_mock.assert_called_once_with(hidden_size, output_size)
    nn_log_softmax_mock.assert_called_once_with(dim=1)


def test_lstm_class_forward(
    nn_embedding_mock: MagicMock,
    nn_lstm_mock: MagicMock,
    nn_linear_mock: MagicMock,
    nn_log_softmax_mock: MagicMock,
    torch_zeros_mock: MagicMock,
) -> None:
    instance = Mock(spec=LSTM)
    input_ = Mock(spec=torch.Tensor)
    input_size, hidden_size, output_size, num_layers = range(4)
    nn_lstm_mock.return_value.return_value = (lstm_out := MagicMock()), None
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
    torch_zeros_mock.assert_has_calls(
        [
            c0 := call(num_layers, instance.embedding.return_value.size.return_value, hidden_size),
            c1 := call().to(input_.device),
            c0,
            c1,
        ]
    )
    instance.lstm.assert_called_once_with(
        instance.embedding.return_value, (zt := torch_zeros_mock.return_value.to.return_value, zt)
    )
    lstm_out.__getitem__.assert_called_once_with((slice(None), -1, slice(None)))
    instance.fc.assert_called_once_with(lstm_out.__getitem__.return_value)
    instance.softmax.assert_called_once_with(instance.fc.return_value)


def test_read_config(mocker: MockerFixture) -> None:
    config = (
        alphabet := ("a", "b", "c"),
        max_name_len := 42,
        rnn_args := (1, 2, 3),
    )
    open_mock = mocker.patch("country_workspace.contrib.name_parser.parser.Path.open")
    open_mock.return_value.__enter__.return_value.readlines.return_value = (
        "".join(alphabet) + "\n",
        str(max_name_len) + "\n",
        " ".join(map(str, rnn_args)) + "\n",
    )

    assert read_config("CNT") == config
    open_mock.assert_called_once()


def test_load_model(mocker: MockerFixture) -> None:
    device_mock = mocker.patch("country_workspace.contrib.name_parser.parser.DEVICE")
    lstm_mock = mocker.patch("country_workspace.contrib.name_parser.parser.LSTM")
    load_mock = mocker.patch("country_workspace.contrib.name_parser.parser.torch.load")
    rnn_args = (1, 2, 3)
    country_code = "CNT"

    assert load_model(country_code, *rnn_args) == lstm_mock.return_value

    lstm_mock.assert_called_once_with(*rnn_args, num_layers=2)
    load_mock.assert_called_once_with(BASE_PATH / MODEL_PATH_TEMPLATE.format(country_code=country_code))
    lstm_mock.return_value.load_state_dict.assert_called_once_with(load_mock.return_value)
    lstm_mock.return_value.to.assert_called_once_with(device_mock)
    lstm_mock.return_value.eval.assert_called_once()


def test_get_line_to_tensor_converter(mocker: MockerFixture) -> None:
    torch_ones_mock = mocker.patch("country_workspace.contrib.name_parser.parser.torch.ones")
    converter = get_line_to_tensor_converter(_alphabet := MagicMock(), _max_name_len := 42)
    assert converter("Name") == torch_ones_mock.return_value.__mul__.return_value


def test_get_parser(mocker: MockerFixture) -> None:
    read_config_mock = mocker.patch("country_workspace.contrib.name_parser.parser.read_config")
    read_config_mock.return_value = (alphabet := Mock(), max_name_len := Mock(), rnn_args := (Mock(),))
    load_model_mock = mocker.patch("country_workspace.contrib.name_parser.parser.load_model")
    get_line_to_tensor_converter_mock = mocker.patch(
        "country_workspace.contrib.name_parser.parser.get_line_to_tensor_converter"
    )
    mocker.patch("country_workspace.contrib.name_parser.parser.torch.exp")
    mocker.patch("country_workspace.contrib.name_parser.parser.torch.argmax")
    name_types_mock = mocker.patch("country_workspace.contrib.name_parser.parser.NAME_TYPES")

    parser = get_parser(country_code := "CNT")
    assert parser("Full Name") == [nt := name_types_mock.__getitem__.return_value, nt]

    read_config_mock.assert_called_once_with(country_code)
    load_model_mock.assert_called_once_with(country_code, *rnn_args)
    get_line_to_tensor_converter_mock.assert_called_once_with(alphabet, max_name_len)
