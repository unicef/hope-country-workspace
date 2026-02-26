from typing import Any
from argparse import ArgumentParser
from django.core.management.base import BaseCommand, CommandError
from country_workspace.utils.gen_rdi import generate, GeneratorConfig, GenerationMode


class Command(BaseCommand):
    help = "Generate synthetic RDI Excel and save to `default_storage`."

    def add_arguments(self, p: ArgumentParser) -> None:
        p.add_argument("office", metavar="OFFICE", help="Office slug.")
        p.add_argument("-H", "--households", type=int, help="[HH mode] Number of households.")
        p.add_argument("--inds-min", type=int, help="[HH mode] Min individuals per household.")
        p.add_argument("--inds-max", type=int, help="[HH mode] Max individuals per household.")
        p.add_argument("-P", "--people", type=int, help="[People mode] Number of people records.")
        p.add_argument("-L", "--locale", help="Faker locale (e.g., en, es_CL).")
        p.add_argument("-S", "--seed", type=int, help="Random seed for reproducible output.")
        p.add_argument(
            "--without-postfix",
            action="store_true",
            help="Generate header columns without sheet postfixes (_h_c/_i_c).",
        )
        p.add_argument("-o", "--filename", help="Output .xlsx name; if omitted, auto-generated.")
        p.add_argument(
            "-X",
            "--exclude-field",
            dest="exclude_fields",
            action="append",
            default=[],
            help="Field name to exclude (base name, repeatable or comma-separated).",
        )

    def _parse_exclude_fields(self, opts: dict[str, Any]) -> tuple[str, ...]:
        raw = opts.get("exclude_fields") or []
        return tuple(dict.fromkeys(s.strip().lower() for ch in raw for s in ch.split(",") if s.strip()))

    def _select_mode_and_validate(self, opts: dict[str, Any]) -> GenerationMode:
        hh_count, people_count = opts.get("households"), opts.get("people")
        inds_min, inds_max = opts.get("inds_min"), opts.get("inds_max")

        hh_mode = hh_count is not None or inds_min is not None or inds_max is not None
        people_mode = people_count is not None
        if hh_mode and people_mode:
            raise CommandError("Cannot mix HH parameters (-H, --inds-*) with People parameters (-P).")
        mode = GenerationMode.HH_IND if hh_mode else GenerationMode.PEOPLE

        if mode is GenerationMode.HH_IND:
            if hh_count is not None and hh_count <= 0:
                raise CommandError("--households must be > 0")
            if (inds_min is None) != (inds_max is None):
                raise CommandError("Pass both --inds-min and --inds-max, or neither.")
            if inds_min is not None and (inds_min <= 0 or inds_min > inds_max):
                raise CommandError("--inds-min must be > 0 and <= --inds-max")
        elif people_count is not None and people_count <= 0:
            raise CommandError("--people must be > 0")
        return mode

    def _build_cfg(self, opts: dict[str, Any], *, mode: GenerationMode, exclude: tuple[str, ...]) -> dict[str, Any]:
        hh_count = opts.get("households")
        inds_min, inds_max = opts.get("inds_min"), opts.get("inds_max")
        people_count = opts.get("people")
        return (
            {"mode": mode, "office_slug": opts["office"]}
            | ({"filename": opts.get("filename")} if opts.get("filename") else {})
            | ({"hh_amount": hh_count} if hh_count is not None else {})
            | ({"inds_per_hh": (inds_min, inds_max)} if inds_min is not None else {})
            | ({"people": people_count} if people_count is not None else {})
            | ({"locale": opts.get("locale")} if opts.get("locale") else {})
            | ({"seed": opts.get("seed")} if opts.get("seed") is not None else {})
            | ({"with_postfix": False} if opts.get("without_postfix") else {})
            | ({"exclude_fields": exclude} if exclude else {})
        )

    def handle(self, *_: Any, **opts: dict) -> None:
        self.stdout.write(self.style.WARNING("Generating RDI..."))

        mode = self._select_mode_and_validate(opts)
        exclude = self._parse_exclude_fields(opts)
        cfg = self._build_cfg(opts, mode=mode, exclude=exclude)
        used_name = generate(GeneratorConfig(**cfg))

        self.stdout.write(self.style.SUCCESS(f"RDI file '{used_name}' generated successfully."))
