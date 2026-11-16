import pytest
from django.template import Context, Template


def render(source: str, **context: str) -> str:
    return Template("{% load workspace_status %}" + source).render(Context(context)).strip()


@pytest.mark.parametrize(
    ("status", "tone"),
    [
        ("SUCCESS", "success"),
        ("success", "success"),
        ("REVIEW_PENDING", "pending"),
        ("FAILURE", "error"),
        ("CANCELLED", "neutral"),
        ("Not scheduled", "neutral"),
    ],
)
def test_status_box_tone(status: str, tone: str) -> None:
    assert f"status-box--{tone}" in render("{% status_box status %}", status=status)


def test_status_box_label_does_not_change_tone() -> None:
    html = render("{% status_box status label %}", status="SUCCESS", label="Réussi")
    assert "status-box--success" in html
    assert "Réussi" in html


def test_status_box_escapes_status() -> None:
    assert "<b>" not in render("{% status_box status %}", status="<b>boom</b>")


def test_status_box_detail() -> None:
    assert "SUCCESS (importing)" in render(
        "{% status_box status detail=detail %}", status="SUCCESS", detail="importing"
    )
    assert "(" not in render("{% status_box status detail=detail %}", status="SUCCESS", detail="")
