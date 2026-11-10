import logging
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


def test_page_heading_keeps_separators_in_data_whole() -> None:
    source = '{% page_heading %}&rsaquo; <a href="/hh/">{{ hh }}</a> &rsaquo; {{ name }}{% endpage_heading %}'
    html = re.sub(
        r">\s+|\s+<", lambda m: m.group().strip(), render(source, hh="Smith \u203a Jones", name="A &rsaquo; B")
    )
    assert '<li><a href="/hh/">Smith \u203a Jones</a></li>' in html
    assert "<h2>A &amp;rsaquo; B</h2>" in html


def test_page_heading_strips_the_real_admin_link() -> None:
    from country_workspace.workspaces.templatetags.workspace_urls import ADMIN_URL

    link = ADMIN_URL.format(url="/admin/x/", query="")
    html = heading(f'&rsaquo; <a href="/hh/">Households</a>{link} &rsaquo; Dixon #0')
    assert "admin-change-link" not in html


def test_page_heading_drops_crumbs_holding_only_an_admin_link() -> None:
    html = heading(f"&rsaquo; {STAR} &rsaquo; Batches")
    assert "page-breadcrumbs" not in html
    assert "<h2>Batches</h2>" in html


def test_icon_renders_inline_svg() -> None:
    html = render('{% icon "home" "text-primary" %}')
    assert html.startswith('<svg class="icon text-primary" viewBox="0 0 24 24" fill="currentColor"')
    assert "<path d=" in html


def test_icon_unknown_name_renders_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert render('{% icon "no-such-icon" %}') == ""
    assert "no-such-icon" in caplog.text
