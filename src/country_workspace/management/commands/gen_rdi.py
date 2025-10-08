from typing import Any
from argparse import ArgumentParser
from django.core.management.base import BaseCommand, CommandError
from country_workspace.utils.gen_rdi import generate, GeneratorConfig


class Command(BaseCommand):
    help = "Generate synthetic RDI Excel and save to `default_storage`."

    def add_arguments(self, p: ArgumentParser) -> None:
        p.add_argument("office", metavar="OFFICE", help="Office slug.")
        p.add_argument("-H", "--households", type=int, help="Number of households.")
        p.add_argument("--inds-min", type=int, help="Min individuals per household.")
        p.add_argument("--inds-max", type=int, help="Max individuals per household.")
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

        if (h := opts.get("households")) is not None and h <= 0:
            raise CommandError("--households must be > 0")

        inds_min, inds_max = opts.get("inds_min"), opts.get("inds_max")
        if (inds_min is None) != (inds_max is None):
            raise CommandError("Pass both --inds-min and --inds-max, or pass neither.")
        if inds_min is not None and (inds_min <= 0 or inds_min > inds_max):
            raise CommandError("--inds-min must be > 0 and <= --inds-max")

        raw_ex = opts.get("exclude_fields") or []
        exclude = tuple(n for chunk in raw_ex for n in (s.strip() for s in chunk.split(",")) if n)

        cfg = (
            {"office_slug": opts["office"]}
            | ({"hh_amount": h} if h is not None else {})
            | ({"inds_per_hh": (inds_min, inds_max)} if inds_min is not None else {})
            | ({"locale": opts.get("locale")} if opts.get("locale") else {})
            | ({"seed": opts.get("seed")} if opts.get("seed") is not None else {})
            | ({"exclude_fields": exclude} if exclude else {})
        )

        generate(GeneratorConfig(**cfg))
        self.stdout.write(self.style.SUCCESS("RDI generated: " + ", ".join(f"{k}={v}" for k, v in cfg.items())))
