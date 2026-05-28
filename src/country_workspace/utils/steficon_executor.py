from __future__ import annotations

from builtins import __build_class__  # noqa: A004
import datetime
from dataclasses import dataclass, field
from decimal import Decimal
import traceback
from typing import Any


class SteficonValidationError(Exception):
    pass


@dataclass
class SteficonResult:
    value: Any = 0
    extra: dict[str, Any] = field(default_factory=dict)


class SteficonExecutor:
    """Execute Steficon-style Python formula code.

    Formula receives:
      - context: dict with "record"
      - result: object exposing "value" and "extra"
    """

    FORBIDDEN_TOKENS = (
        "__import__",
        "import ",
        "\nimport ",
        " from ",
        " delete",
        " save",
        " eval",
        " exec",
    )

    def __init__(self, data: dict[str, Any], code: str) -> None:
        self.data = data
        self.code = code

    def execute(self) -> dict[str, Any]:
        result = SteficonResult(value=dict(self.data))
        context = {"record": dict(self.data)}
        gl = self._globals()
        locals_: dict[str, Any] = {
            "context": context,
            "result": result,
        }
        exec(self.code, gl, locals_)  # noqa: S102

        if isinstance(result.value, dict):
            return result.value
        if isinstance(context.get("record"), dict):
            return context["record"]
        raise SteficonValidationError("Steficon formula must produce a dict in result.value or context['record']")

    @classmethod
    def validate(cls, code: str) -> None:
        if any(token in code for token in cls.FORBIDDEN_TOKENS):
            raise SteficonValidationError("Steficon formula contains forbidden statements")
        try:
            compile(code, "<steficon_formula>", mode="exec")
        except SyntaxError as exc:
            tb = traceback.format_exc(limit=-1)
            message = tb.split('<steficon_formula>", ')[-1]
            raise SteficonValidationError(message) from exc

    @staticmethod
    def _globals() -> dict[str, Any]:
        return {
            "__builtins__": {
                "__build_class__": __build_class__,
                "__name__": __name__,
                "date": datetime.date,
                "datetime": datetime.datetime,
                "timedelta": datetime.timedelta,
                "Decimal": Decimal,
                "complex": complex,
                "dict": dict,
                "float": float,
                "frozenset": frozenset,
                "int": int,
                "list": list,
                "memoryview": memoryview,
                "range": range,
                "set": set,
                "str": str,
                "tuple": tuple,
            }
        }
