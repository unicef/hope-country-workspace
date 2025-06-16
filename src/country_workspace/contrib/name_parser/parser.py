from collections.abc import Callable
from pathlib import Path

import torch
from torch import nn

Parser = Callable[[str], list[str]]

NAME_TYPES = "given_name", "middle_name", "family_name"

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

BASE_PATH = Path(__file__).parent.parent.parent


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


def get_parser(country_code: str) -> Parser:
    with (BASE_PATH / f"data/name_parser/models/{country_code}.txt").open() as f:
        lines = f.readlines()

    unknown = "_"
    alphabet = tuple(lines[0])
    alphabet_len = len(alphabet)
    name_max_len = int(lines[1])
    rnn_args = map(int, lines[2].split())

    rnn = LSTM(*rnn_args, num_layers=2)
    rnn.load_state_dict(torch.load(BASE_PATH / f"data/name_parser/models/{country_code}.pt"))
    rnn.to(DEVICE)
    rnn.eval()

    def letter_to_index(letter: str) -> int:
        return alphabet.index(letter) if letter in alphabet else alphabet.index(unknown)

    oob = alphabet_len + 1

    def line_to_tensor(line: str) -> torch.Tensor:
        tensor = torch.ones(name_max_len, dtype=torch.long) * oob
        for li, letter in enumerate(line):
            tensor[li] = letter_to_index(letter)
        return tensor

    def parser(name: str) -> list[str]:
        name_tokens = [line_to_tensor(i) for i in name.split()]
        out = [rnn(i.unsqueeze(0).to(DEVICE)) for i in name_tokens]
        probs = [torch.exp(i) for i in out]
        out = [torch.argmax(i) for i in probs]
        return [NAME_TYPES[i.item()] for i in out]

    return parser
