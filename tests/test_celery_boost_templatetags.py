import pytest

from country_workspace.workspaces.templatetags.celery_boost import is_celery_info_visible


@pytest.mark.parametrize(
    ("key", "is_superuser", "expected"),
    [
        ("error", False, True),
        ("error", True, True),
        ("result", False, False),
        ("result", True, True),
        ("status", False, True),
        ("traceback", False, False),
        ("traceback", True, False),
        ("task_args", False, False),
        ("children", True, False),
    ],
)
def test_is_celery_info_visible(key: str, is_superuser: bool, expected: bool) -> None:
    assert is_celery_info_visible(key, is_superuser) is expected
