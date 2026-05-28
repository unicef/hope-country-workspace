import pytest

from country_workspace.utils.steficon_executor import SteficonExecutor, SteficonValidationError


def test_validate_accepts_valid_formula():
    SteficonExecutor.validate("result.value = context['record']")


@pytest.mark.parametrize("code", ["import os", "__import__('os')", "exec('x=1')", "eval('1+1')"])
def test_validate_rejects_forbidden_tokens(code):
    with pytest.raises(SteficonValidationError):
        SteficonExecutor.validate(code)


def test_execute_uses_result_value_dict():
    data = {"sex": "M"}
    code = "result.value = context['record']; result.value['sex'] = 'MALE'"
    executor = SteficonExecutor(data=data, code=code)
    result = executor.execute()
    assert result == {"sex": "MALE"}


def test_execute_falls_back_to_context_record():
    data = {"status": "PENDING"}
    code = "context['record']['status'] = 'ACTIVE'"
    executor = SteficonExecutor(data=data, code=code)
    result = executor.execute()
    assert result == {"status": "ACTIVE"}
