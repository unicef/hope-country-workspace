from pathlib import Path
from typing import TYPE_CHECKING

from country_workspace import VERSION

if TYPE_CHECKING:
    from country_workspace.versioning.management.manager import Manager

# sample_folder = Path(__file__).parent / "scripts"
# scripts = [
#     (sample_folder / "0001_test.py"),
#     (sample_folder / "0002_test.py"),
#     (sample_folder / "0003_test.py"),
# ]

#
# @pytest.fixture()
# def version1():
#     from testutils.factories import VersionFactory
#
#     f = sample_folder / "0001_test.py"
#     return VersionFactory(name=f.name, version=VERSION)
#
#
# @pytest.fixture()
# def version2():
#     from testutils.factories import VersionFactory
#
#     f = sample_folder / "0002_test.py"
#     return VersionFactory(name=f.name, version=VERSION)
#
#
# @pytest.fixture()
# def version3():
#     from testutils.factories import VersionFactory
#
#     f = sample_folder / "0003_test.py"
#     return VersionFactory(name=f.name, version=VERSION)
#
#
# @pytest.fixture()
# def manager():
#     return Manager(sample_folder)


def test_manager_1(manager: "Manager", scripts: list[Path]) -> None:
    assert manager.max_version == 3
    assert manager.max_applied_version == 0
    assert manager.applied == []
    assert manager.existing == scripts


def test_manager_2(version1, manager: "Manager", scripts: list[Path]):
    assert manager.max_version == 3
    assert manager.max_applied_version == 1
    assert manager.applied == [version1.name]
    assert manager.existing == scripts


def test_manager_forward(manager: "Manager", scripts: list[Path]):
    from country_workspace.versioning.models import Version

    assert manager.applied == []
    manager.forward(1)
    assert manager.applied == [scripts[0].name]

    assert Version.objects.filter(name=scripts[0].name, version=VERSION).exists()
    assert not Version.objects.filter(name=scripts[1].name, version=VERSION).exists()
    manager.forward(2)
    assert Version.objects.filter(name=scripts[0].name, version=VERSION).exists()
    assert Version.objects.filter(name=scripts[1].name, version=VERSION).exists()
    manager.forward(manager.max_version)


def test_manager_backward(version1, version2, version3, manager: "Manager", scripts: list[Path]):
    from country_workspace.versioning.models import Version

    assert manager.applied == [version1.name, version2.name, version3.name]
    ret = manager.backward(2)
    assert [r[0] for r in ret] == [scripts[2].name]

    assert manager.applied == [scripts[0].name, scripts[1].name]
    assert list(Version.objects.values_list("name", flat=True)) == [scripts[0].name, scripts[1].name]


def test_manager_zero(version1, manager: "Manager", scripts: list[Path]):
    from country_workspace.versioning.models import Version

    manager.zero()
    assert manager.applied == []
    assert not Version.objects.filter(name=scripts[0].name, version=VERSION).exists()
    assert not Version.objects.filter(name=scripts[1].name, version=VERSION).exists()
