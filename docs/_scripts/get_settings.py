import mkdocs_gen_files

from country_workspace.config import env

MD_HEADER = """# Setttings

"""
MD_LINE = """
### {key}
_Default_: `{default_value}`

{help}

"""
DEV_LINE = """
__Suggested value for development__: `{develop_value}`
"""

OUTFILE = "settings.md"
with mkdocs_gen_files.open(OUTFILE, "w") as f:
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
mkdocs_gen_files.set_edit_path(OUTFILE, "get_settings.py")
