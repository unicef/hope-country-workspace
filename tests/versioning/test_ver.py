from pathlib import Path
from typing import TYPE_CHECKING

from country_workspace import VERSION

if TYPE_CHECKING:
    from country_workspace.versioning.management.manager import Manager


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
    from country_workspace.versioning.models import Script

    assert manager.applied == []
    manager.forward(1)
    assert manager.applied == [scripts[0].name]

    assert Script.objects.filter(name=scripts[0].name, version=VERSION).exists()
    assert not Script.objects.filter(name=scripts[1].name, version=VERSION).exists()
    manager.forward(2)
    assert Script.objects.filter(name=scripts[0].name, version=VERSION).exists()
    assert Script.objects.filter(name=scripts[1].name, version=VERSION).exists()
    manager.forward(manager.max_version)


def test_manager_backward(version1, version2, version3, manager: "Manager", scripts: list[Path]):
    from country_workspace.versioning.models import Script

    assert manager.applied == [version1.name, version2.name, version3.name]
    ret = manager.backward(2)
    assert [r[0] for r in ret] == [scripts[2].name]

    assert manager.applied == [scripts[0].name, scripts[1].name]
    assert list(Script.objects.values_list("name", flat=True)) == [scripts[0].name, scripts[1].name]


def test_manager_zero(version1, manager: "Manager", scripts: list[Path]):
    from country_workspace.versioning.models import Script

    manager.zero()
    assert manager.applied == []
    assert not Script.objects.filter(name=scripts[0].name, version=VERSION).exists()
    assert not Script.objects.filter(name=scripts[1].name, version=VERSION).exists()
