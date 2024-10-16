import importlib.util
import re
from pathlib import Path
from typing import Callable

from country_workspace import VERSION
from country_workspace.versioning.models import Version

regex = re.compile(r"(\d+).*")
default_folder = Path(__file__).parent.parent / "scripts"


def get_version(filename):
    if m := regex.match(filename):
        return int(m.group(1))
    return None


def get_funcs(filename: Path, direction: str = "forward"):
    if not filename.exists():  # pragma: no cover
        raise FileNotFoundError(filename)
    spec = importlib.util.spec_from_file_location("version", filename.absolute())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    funcs = []
    for op in module.Version.operations:
        if isinstance(op, (list, tuple)):
            if direction == "forward":
                funcs.append(op[0])
            else:
                funcs.append(op[1])
        else:
            if direction == "forward":
                funcs.append(op)
            else:
                funcs.append(lambda: True)

    return funcs


class Manager:
    def __init__(self, folder: Path = default_folder):
        self.folder = folder
        self.existing = []
        self.applied = list(Version.objects.order_by("name").values_list("name", flat=True))
        self.max_version = 0
        self.max_applied_version = 0
        for applied in self.applied:
            self.max_applied_version = max(get_version(applied), self.max_applied_version)

        for filename in sorted(self.folder.iterdir()):
            if v := get_version(filename.name):
                self.existing.append(filename)
                self.max_version = max(self.max_version, v)

    def zero(self):
        self.backward(0)

    def forward(self, to_num) -> list[tuple[Path, list[Callable[[None], None]]]]:
        print("Upgrading...")
        processed = []
        for entry in self.existing:
            if get_version(entry.stem) > to_num:
                break
            if entry.name not in self.applied:
                funcs = get_funcs(entry, direction="forward")
                print(f"    Applying {entry.stem}")
                for func in funcs:
                    func()
                Version.objects.create(name=entry.name, version=VERSION)
                processed.append((entry, funcs))
        self.applied = list(Version.objects.order_by("name").values_list("name", flat=True))
        return processed

    def backward(self, to_num) -> list[tuple[Path, list[Callable[[None], None]]]]:
        print("Downgrading...")
        processed = []
        for entry in reversed(self.applied):
            if get_version(entry) <= to_num:
                break
            file_path = Path(self.folder) / entry
            funcs = get_funcs(file_path, direction="backward")
            print(f"  Discharging {file_path.stem}")
            for func in funcs:
                func()
            Version.objects.get(name=file_path.name).delete()
            processed.append((entry, funcs))
        self.applied = list(Version.objects.order_by("name").values_list("name", flat=True))
        return processed
