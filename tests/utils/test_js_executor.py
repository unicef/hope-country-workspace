import json
from unittest.mock import patch

import pytest

from country_workspace.utils.js_executor import JavaScriptExecutor, JsValidationError


def test_execute_with_function_declaration():
    data = [{"name": "John"}, {"name": "Jane"}]
    code = "function process(data) { return data.length; }"
    executor = JavaScriptExecutor(data=data, code=code)
    result = executor.execute()
    assert result == 2


def test_execute_with_const_function():
    data = [{"name": "John"}]
    code = "const process = function(data) { return data[0].name; }"
    executor = JavaScriptExecutor(data=data, code=code)
    result = executor.execute()
    assert result == "John"


def test_execute_with_no_function_name():
    data = [{"name": "John"}]
    code = "console.log('hello');"
    executor = JavaScriptExecutor(data=data, code=code)
    with pytest.raises(JsValidationError, match=r"JavaScript function name not found"):
        executor.execute()


def test_execute_with_js_runtime_error():
    data = [{"name": "John"}]
    code = "function process(data) { return undefined.property; }"
    executor = JavaScriptExecutor(data=data, code=code)
    with pytest.raises(JsValidationError, match=r"JavaScript error:"):
        executor.execute()


def test_get_js_func_name_function_declaration():
    code = "function myFunction(data) { return data; }"
    result = JavaScriptExecutor._get_js_func_name(code)
    assert result == "myFunction"


def test_get_js_func_name_const_function():
    code = "const myFunction = function(data) { return data; }"
    result = JavaScriptExecutor._get_js_func_name(code)
    assert result == "myFunction"


def test_get_js_func_name_arrow_function():
    code = "const myFunction = (data) => { return data; }"
    result = JavaScriptExecutor._get_js_func_name(code)
    assert result == "myFunction"


def test_get_js_func_name_arrow_function_no_parentheses():
    code = "const myFunction = data => { return data; }"
    result = JavaScriptExecutor._get_js_func_name(code)
    assert result == "myFunction"


def test_get_js_func_name_with_underscores():
    code = "function my_function_name(data) { return data; }"
    result = JavaScriptExecutor._get_js_func_name(code)
    assert result == "my_function_name"


def test_get_js_func_name_no_match():
    code = "console.log('hello');"
    result = JavaScriptExecutor._get_js_func_name(code)
    assert result is None


def test_generate_js_variable_name():
    var_name = JavaScriptExecutor._generate_js_variable_name()
    assert len(var_name) == 6
    assert var_name[0].isalpha()
    assert all(c.isalnum() for c in var_name)


def test_generate_js_variable_name_custom_length():
    var_name = JavaScriptExecutor._generate_js_variable_name(length=10)
    assert len(var_name) == 10
    assert var_name[0].isalpha()
    assert all(c.isalnum() for c in var_name)


def test_append_func_call():
    data = [{"name": "John"}]
    code = "function process(data) { return data; }"
    executor = JavaScriptExecutor(data=data, code=code)
    result = executor._append_func_call("process")
    assert code in result
    assert json.dumps(data) in result
    assert "var result = process(" in result
    assert result.strip().endswith("result;")


@patch("country_workspace.utils.js_executor.dukpy.evaljs")
def test_eval_js_success(mock_evaljs):
    mock_evaljs.return_value = "test result"
    result = JavaScriptExecutor._eval_js("console.log('test');")
    assert result == "test result"
    mock_evaljs.assert_called_once_with("console.log('test');")


@patch("country_workspace.utils.js_executor.dukpy.evaljs")
def test_eval_js_runtime_error(mock_evaljs):
    from dukpy._dukpy import JSRuntimeError

    mock_evaljs.side_effect = JSRuntimeError("ReferenceError: x is not defined")
    with pytest.raises(JsValidationError, match=r"JavaScript error: ReferenceError: x is not defined"):
        JavaScriptExecutor._eval_js("x + y;")


@patch("country_workspace.utils.js_executor.dukpy.evaljs")
def test_is_valid_js_valid_code(mock_evaljs):
    mock_evaljs.return_value = True
    code = "function test(data) { return data; }"
    result = JavaScriptExecutor.is_valid_js(code)
    assert result is True


@patch("country_workspace.utils.js_executor.dukpy.evaljs")
def test_is_valid_js_invalid_code(mock_evaljs):
    from dukpy._dukpy import JSRuntimeError

    mock_evaljs.side_effect = JSRuntimeError("SyntaxError")
    code = "function test(data { return data; }"
    result = JavaScriptExecutor.is_valid_js(code)
    assert result is False


def test_is_valid_js_no_function_name():
    code = "console.log('hello');"
    result = JavaScriptExecutor.is_valid_js(code)
    assert result is False


def test_execute_with_empty_data():
    data = []
    code = "function process(data) { return data.length; }"
    executor = JavaScriptExecutor(data=data, code=code)
    result = executor.execute()
    assert result == 0
