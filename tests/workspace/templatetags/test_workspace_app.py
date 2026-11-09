import re

from django.template import Context, Template

from country_workspace import VERSION

STAR = '<a class="admin-change-link" target="_admin" href="/admin/x/">\n<span class="icon icon-star1"></span>\n</a>'


def render(source: str, **context: str) -> str:
    return Template("{% load workspace_app %}" + source).render(Context(context)).strip()


def heading(title: str) -> str:
    html = render("{% page_heading %}" + title + "{% endpage_heading %}")
    return re.sub(r">\s+|\s+<", lambda m: m.group().strip(), html)


def test_app_version() -> None:
    assert render("{% app_version %}") == VERSION


def test_page_heading_splits_crumbs_and_title() -> None:
    html = heading(f'&rsaquo; <a href="/hh/">Households</a>{STAR} &rsaquo; Dixon #0{STAR}')
    crumbs, title = html.split('<div class="page-title-row">')
    assert '<li><a href="/hh/">Households</a></li>' in crumbs
    assert "admin-change-link" not in crumbs
    assert "<h2>Dixon #0</h2>" in title
    assert '<span class="page-flags"><a class="admin-change-link"' in title


def test_page_heading_without_crumbs() -> None:
    html = heading("&rsaquo; Batches")
    assert "page-breadcrumbs" not in html
    assert "<h2>Batches</h2>" in html
    assert "page-flags" not in html


def test_page_heading_plain_title() -> None:
    assert "<h2>Welcome</h2>" in heading("Welcome")


def test_page_heading_escapes_context() -> None:
    html = render("{% page_heading %}&rsaquo; {{ name }}{% endpage_heading %}", name="<b>x</b>")
    assert "<b>" not in html


def test_icon_renders_inline_svg() -> None:
    html = render('{% icon "home" "text-primary" %}')
    assert html.startswith('<svg class="icon text-primary" viewBox="0 0 24 24" fill="currentColor"')
    assert "<path d=" in html
