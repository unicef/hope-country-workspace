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
            "-X",
            "--exclude-field",
            dest="exclude_fields",
            action="append",
            default=[],
            help="Field name to exclude (base name, repeatable or comma-separated).",
        )

    def handle(self, *_: Any, **opts: dict) -> None:
        self.stdout.write(self.style.WARNING("Generating RDI..."))

        hh_count, people_count = opts.get("households"), opts.get("people")
        inds_min, inds_max = opts.get("inds_min"), opts.get("inds_max")

        # Auto-detect mode
        hh_mode = hh_count is not None or inds_min is not None or inds_max is not None
        people_mode = people_count is not None

        if hh_mode and people_mode:
            raise CommandError("Cannot mix HH parameters (-H, --inds-*) with People parameters (-P).")
        mode = GenerationMode.HH_IND if hh_mode else GenerationMode.PEOPLE
        if mode == GenerationMode.HH_IND:
            if hh_count is not None and hh_count <= 0:
                raise CommandError("--households must be > 0")
            if (inds_min is None) != (inds_max is None):
                raise CommandError("Pass both --inds-min and --inds-max, or neither.")
            if inds_min is not None and (inds_min <= 0 or inds_min > inds_max):
                raise CommandError("--inds-min must be > 0 and <= --inds-max")
        elif people_count is not None and people_count <= 0:
            raise CommandError("--people must be > 0")

        exclude = tuple(
            n for chunk in (opts.get("exclude_fields") or []) for n in (s.strip() for s in chunk.split(",")) if n
        )
        cfg = (
            {"mode": mode, "office_slug": opts["office"]}
            | ({"hh_amount": hh_count} if hh_count is not None else {})
            | ({"inds_per_hh": (inds_min, inds_max)} if inds_min is not None else {})
            | ({"people": people_count} if people_count is not None else {})
            | ({"locale": opts.get("locale")} if opts.get("locale") else {})
            | ({"seed": opts.get("seed")} if opts.get("seed") is not None else {})
            | ({"exclude_fields": exclude} if exclude else {})
        )

        generate(GeneratorConfig(**cfg))

        self.stdout.write(self.style.SUCCESS(f"RDI generated: {', '.join(f'{k}={v}' for k, v in cfg.items())}."))
