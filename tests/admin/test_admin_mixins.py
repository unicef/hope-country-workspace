import json
import pytest
from django_celery_results.models import TaskResult
from country_workspace.admin.mixins import JobErrorDisplayMixin


class MockJob:
    def __init__(self, result_id=None):
        self.curr_async_result_id = result_id


class TestJobErrorDisplayMixin:
    @pytest.fixture
    def mixin(self):
        return JobErrorDisplayMixin()

    def test_formatted_error_no_obj(self, mixin: JobErrorDisplayMixin):
        assert mixin.result(None) == ""

    def test_formatted_error_no_result_id(self, mixin):
        obj = MockJob(None)
        assert mixin.result(obj) == ""

    def test_formatted_error_no_task_result(self, mixin, db):
        obj = MockJob("missing-id")
        assert mixin.result(obj) == ""

    def test_formatted_error_empty_result(self, mixin, db):
        TaskResult.objects.create(task_id="empty-id", result=None)
        obj = MockJob("empty-id")
        assert mixin.result(obj) == ""

    def test_formatted_error_json_string(self, mixin, db):
        data = {"error": "test error"}
        TaskResult.objects.create(task_id="json-id", result=json.dumps(data))
        obj = MockJob("json-id")
        result = mixin.result(obj)
        assert "<pre>" in result
        assert "test error" in result

    def test_formatted_error_dict(self, mixin, db):
        data = {"error": "test error"}
        TaskResult.objects.create(task_id="dict-id", result=data)
        obj = MockJob("dict-id")
        result = mixin.result(obj)
        assert "<pre>" in result
        assert "test error" in result

    def test_formatted_error_invalid_json(self, mixin, db):
        TaskResult.objects.create(task_id="invalid-id", result="invalid json")
        obj = MockJob("invalid-id")
        result = mixin.result(obj)
        assert "<pre>" in result
        assert "invalid json" in result
