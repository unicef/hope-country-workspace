from pathlib import Path

from country_workspace.config import env

MD_HEADER = """
# Setttings

"""
MD_LINE = """
### {key}
_Default_: `{default_value}`

{help}

"""
DEV_LINE = """
__Suggested value for development__: `{develop_value}`
"""

with (Path(__file__).parent.parent / "src" / "settings.md").open("w") as f:

    f.write(MD_HEADER)
    for entry, cfg in sorted(env.config.items()):
        f.write(
            MD_LINE.format(
                key=entry, default_value=cfg["default"], develop_value=env.get_develop_value(entry), help=cfg["help"]
            )
        )
        if env.get_develop_value(entry):
            f.write(
                DEV_LINE.format(
                    key=entry,
                    default_value=cfg["default"],
                    develop_value=env.get_develop_value(entry),
                    help=cfg["help"],
                )
            )
