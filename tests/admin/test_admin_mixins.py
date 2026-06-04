import json
import pytest
from unittest.mock import MagicMock, patch
from django_celery_results.models import TaskResult
from country_workspace.admin.mixins import JobErrorDisplayMixin


class MockJob:
    def __init__(self, result_id=None, task_info=None):
        self.curr_async_result_id = result_id
        self.task_info = task_info or {}


class TestJobErrorDisplayMixin:
    @pytest.fixture
    def mixin(self):
        return JobErrorDisplayMixin()

    def test_formatted_error_no_obj(self, mixin: JobErrorDisplayMixin):
        assert mixin.result(None) == ""

    def test_error_no_obj(self, mixin: JobErrorDisplayMixin):
        assert mixin.error(None) == ""

    def test_error_empty_task_info(self, mixin: JobErrorDisplayMixin):
        assert mixin.error(MockJob(task_info={})) == ""

    def test_error_with_message(self, mixin: JobErrorDisplayMixin):
        obj = MockJob(task_info={"error": "something went wrong"})
        assert mixin.error(obj) == "something went wrong"

    def test_error_task_failure_takes_precedence_over_application_errors(self, mixin: JobErrorDisplayMixin):
        data = {"errors": ["application error"]}
        with patch("django_celery_results.models.TaskResult.objects.filter") as mock_filter:
            mock_result = MagicMock()
            mock_result.result = data
            mock_filter.return_value.first.return_value = mock_result

            obj = MockJob("task-id", task_info={"error": "task failed"})
            assert mixin.error(obj) == "task failed"

    def test_error_application_errors_from_result(self, mixin: JobErrorDisplayMixin):
        data = {"errors": ["first error", "second error"], "rdp_id": 6}
        with patch("django_celery_results.models.TaskResult.objects.filter") as mock_filter:
            mock_result = MagicMock()
            mock_result.result = data
            mock_filter.return_value.first.return_value = mock_result

            obj = MockJob("task-id", task_info={"error": ""})
            result = mixin.error(obj)

            assert "<pre>" in result
            assert "first error" in result
            assert "second error" in result

    def test_error_empty_application_errors_list(self, mixin: JobErrorDisplayMixin):
        data = {"errors": []}
        with patch("django_celery_results.models.TaskResult.objects.filter") as mock_filter:
            mock_result = MagicMock()
            mock_result.result = data
            mock_filter.return_value.first.return_value = mock_result

            obj = MockJob("task-id", task_info={})
            assert mixin.error(obj) == ""

    def test_format_application_errors_non_dict(self, mixin: JobErrorDisplayMixin):
        assert mixin._format_application_errors("not a dict") == ""

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

    def test_formatted_error_dict_mocked(self, mixin):
        data = {"error": "test error"}
        with patch("django_celery_results.models.TaskResult.objects.filter") as mock_filter:
            mock_result = MagicMock()
            mock_result.result = data
            mock_filter.return_value.first.return_value = mock_result

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
