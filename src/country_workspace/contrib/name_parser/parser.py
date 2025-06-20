from collections.abc import Callable
from pathlib import Path

import torch
from torch import nn

Parser = Callable[[str], list[str]]

NAME_TYPES = "given_name", "middle_name", "family_name"

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

BASE_PATH = Path(__file__).parent.parent.parent

CONFIG_PATH_TEMPLATE = "data/name_parser/models/{country_code}.txt"
MODEL_PATH_TEMPLATE = "data/name_parser/models/{country_code}.pt"


class LSTM(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, output_size: int, num_layers: int = 1) -> None:
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        # The nn.Embedding layer returns a new tensor with dimension (sequence_length, 1, hidden_size)
        self.embedding = nn.Embedding(input_size, hidden_size)
        # LSTM layer expects a tensor of dimension (batch_size, sequence_length, hidden_size).
        self.lstm = nn.LSTM(hidden_size, hidden_size, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, output_size)
        self.softmax = nn.LogSoftmax(dim=1)

    def forward(self, input_: torch.Tensor) -> torch.Tensor:
        embedded = self.embedding(input_.type(torch.IntTensor).to(input_.device))
        h0 = torch.zeros(self.num_layers, embedded.size(0), self.hidden_size).to(input_.device)
        c0 = torch.zeros(self.num_layers, embedded.size(0), self.hidden_size).to(input_.device)
        out, _ = self.lstm(embedded, (h0, c0))
        out = out[:, -1, :]  # get the output of the last time step
        out = self.fc(out)
        return self.softmax(out)


Alphabet = tuple[str, ...]
ModelArgs = tuple[int, ...]
UNKNOWN_CHAR = "_"


def read_config(country_code: str) -> tuple[Alphabet, int, ModelArgs]:
    with (BASE_PATH / CONFIG_PATH_TEMPLATE.format(country_code=country_code)).open() as f:
        lines = tuple(line.rstrip("\n") for line in f.readlines())

    return (
        tuple(lines[0]),
        int(lines[1]),
        tuple(map(int, lines[2].split())),
    )


def load_model(country_code: str, *args: int) -> nn.Module:
    rnn = LSTM(*args, num_layers=2)
    rnn.load_state_dict(torch.load(BASE_PATH / MODEL_PATH_TEMPLATE.format(country_code=country_code)))
    rnn.to(DEVICE)
    rnn.eval()
    return rnn


def get_line_to_tensor_converter(alphabet: Alphabet, max_name_len: int) -> Callable[[str], torch.Tensor]:
    oob = len(alphabet) + 1

    def letter_to_index(letter: str) -> int:
        return alphabet.index(letter) if letter in alphabet else alphabet.index(UNKNOWN_CHAR)

    def line_to_tensor(line: str) -> torch.Tensor:
        tensor = torch.ones(max_name_len, dtype=torch.long) * oob
        for li, letter in enumerate(line):
            tensor[li] = letter_to_index(letter)
        return tensor

    return line_to_tensor


def get_parser(country_code: str) -> Parser:
    alphabet, max_name_len, rnn_args = read_config(country_code)
    rnn = load_model(country_code, *rnn_args)
    line_to_tensor = get_line_to_tensor_converter(alphabet, max_name_len)

    def parser(name: str) -> list[str]:
        name_tokens = [line_to_tensor(i) for i in name.split()]
        out = [rnn(i.unsqueeze(0).to(DEVICE)) for i in name_tokens]
        probs = [torch.exp(i) for i in out]
        out = [torch.argmax(i) for i in probs]
        return [NAME_TYPES[i.item()] for i in out]

    return parser
