from __future__ import annotations

import re
from typing import LiteralString

from re import Match
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files
    from mkdocs.structure.pages import Page

change_log = "/changelog.md"


def on_page_markdown(markdown: str, *, page: Page, config: MkDocsConfig, files: Files) -> str:
    # Replace callback
    def replace(match: Match) -> str:
        op, args = match.groups()
        args = args.strip()
        if op in ["added", "add"]:
            return badge_for_added(args, page, files)
        if op in ["changed", "cgh"]:
            return badge_for_change(args, page, files)

        raise RuntimeError(f"Unknown operation: {op}")

    # Find and replace all external asset URLs in current page
    return re.sub(r"<!-- ver:(\w+)(.*?) -->", replace, markdown, flags=re.IGNORECASE | re.MULTILINE)


def _badge(icon: str, text: str = "", type_: str = "") -> str:
    classes = f"mdx-badge mdx-badge--{type_}" if type_ else "mdx-badge"
    return "".join(
        [
            f'<span class="{classes}">',
            *([f'<span class="mdx-badge__icon">{icon}</span>'] if icon else []),
            *([f'<span class="mdx-badge__text">{text}</span>'] if text else []),
            "</span>",
        ]
    )


def badge_for_added(text: LiteralString, page: Page, files: Files) -> str:
    spec = text.replace(".", "")

    icon = "octicons-file-added-16"
    return _badge(icon=f"[:{icon}:]('Version added')", text=f" [{text}]({change_log}#{spec})" if spec else "")


def badge_for_change(text: LiteralString, page: Page, files: Files) -> str:
    spec = text.replace(".", "")
    icon = "material-square-edit-outline"
    return _badge(icon=f"[:{icon}:]('Version added')", text=f" [{text}]({change_log}#{spec})" if spec else "")
