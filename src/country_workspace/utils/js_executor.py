import json
import re
import secrets
import string
from typing import Any

import dukpy
from dukpy._dukpy import JSRuntimeError


class JsValidationError(Exception):
    pass


class JavaScriptExecutor:
    def __init__(self, data: list[dict], code: str) -> None:
        self.data = data
        self.code = code

    def execute(self) -> Any:
        func_name = self._get_js_func_name(self.code)
        if not func_name:
            raise JsValidationError("JavaScript function name not found")

        full_code = self._append_func_call(func_name=func_name)
        return self._eval_js(full_code)

    @staticmethod
    def _eval_js(code: str) -> Any:
        try:
            return dukpy.evaljs(code)
        except JSRuntimeError as e:
            msg = f"JavaScript error: {e}"
            raise JsValidationError(msg)

    def _append_func_call(self, func_name: str) -> str:
        var_name = self._generate_js_variable_name()
        return f"""{self.code.strip()}
                var {var_name} = {json.dumps(self.data)};
                var result = {func_name}({var_name});
                result;"""

    @staticmethod
    def _get_js_func_name(code: str) -> str | None:
        # Pattern 1: function myFunc(...) { ... }
        match = re.search(r"function\s+([a-zA-Z_$][\w$]*)\s*\(", code)
        if match:
            return match.group(1)

        # Pattern 2: const myFunc = function(...) { ... }
        match = re.search(r"\bconst\s+([a-zA-Z_$][\w$]*)\s*=\s*function\s*\(", code)
        if match:
            return match.group(1)

        # Pattern 3: const myFunc = (...) => { ... }
        match = re.search(r"\bconst\s+([a-zA-Z_$][\w$]*)\s*=\s*\(?[^\)]*\)?\s*=>", code)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def _generate_js_variable_name(length: int = 6) -> str:
        first_char = secrets.choice(string.ascii_letters)
        other_chars = string.ascii_letters + string.digits
        rest = "".join(secrets.choice(other_chars) for _ in range(length - 1))

        return f"{first_char}{rest}"

    @classmethod
    def is_valid_js(cls, js_code: str) -> bool:
        try:
            cls._eval_js(js_code)
            return cls._get_js_func_name(js_code)
        except JsValidationError:
            return False
