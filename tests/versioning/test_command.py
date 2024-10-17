from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command

import pytest


def test_command_list(version1, test_scripts_folder):
    out = StringIO()
    with mock.patch("country_workspace.versioning.management.manager.Manager.default_folder", test_scripts_folder):
        call_command("upgradescripts", ["list"], stdout=out)
        ret = str(out.getvalue())
        assert ret == "[x] 0001_test\n[ ] 0002_test\n[ ] 0003_test\n"


@pytest.mark.parametrize("verbosity", [0, 1])
def test_command_apply_all(version1, test_scripts_folder, verbosity):
    out = StringIO()
    with mock.patch("country_workspace.versioning.management.manager.Manager.default_folder", test_scripts_folder):
        call_command("upgradescripts", ["-v", verbosity, "apply"], stdout=out)
        ret = str(out.getvalue())
        assert ret == "Upgrading...\n   Applying 0002_test\n   Applying 0003_test\n"


def test_command_apply(version1, test_scripts_folder):
    out = StringIO()
    with mock.patch("country_workspace.versioning.management.manager.Manager.default_folder", test_scripts_folder):
        call_command("upgradescripts", ["apply", "2"], stdout=out)
        ret = str(out.getvalue())
        assert ret == "Upgrading...\n   Applying 0002_test\n"


def test_command_apply_fake(version1, test_scripts_folder):
    out = StringIO()
    with mock.patch("country_workspace.versioning.management.manager.Manager.default_folder", test_scripts_folder):
        call_command("upgradescripts", ["apply", "2", "--fake"], stdout=out)
        ret = str(out.getvalue())
        assert ret == "Upgrading...\n   Applying 0002_test (fake)\n"


def test_command_backward(version1, version2, test_scripts_folder):
    out = StringIO()
    with mock.patch("country_workspace.versioning.management.manager.Manager.default_folder", test_scripts_folder):
        call_command("upgradescripts", ["apply", "1"], stdout=out)
        ret = str(out.getvalue())
        assert ret == "Downgrading...\n   Discharging 0002_test\n"


def test_command_zero(version1, test_scripts_folder):
    out = StringIO()
    with mock.patch("country_workspace.versioning.management.manager.Manager.default_folder", test_scripts_folder):
        call_command("upgradescripts", ["apply", "zero"], stdout=out)
        ret = str(out.getvalue())
        assert ret == "Downgrading...\n   Discharging 0001_test\n"


def test_command_create(version1, test_scripts_folder):
    out = StringIO()
    try:
        with mock.patch("country_workspace.versioning.management.manager.Manager.default_folder", test_scripts_folder):
            call_command("upgradescripts", ["create", "--label", "sample"], stdout=out)
            ret = str(out.getvalue())
            assert ret == "Created script 0004_sample.py\n"
    finally:
        if (Path(test_scripts_folder) / "0004_sample.py").exists():
            (Path(test_scripts_folder) / "0004_sample.py").unlink()
