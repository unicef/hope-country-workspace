import sys
import vcr
from collections.abc import Callable
from typing import Any
from pathlib import Path
from vcr.record_mode import RecordMode
from vcr.errors import CannotOverwriteExistingCassetteException

from constance import config
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import BaseCommand, call_command
from django.core.management.base import CommandError
from django.contrib.sites.models import Site
from django.db import transaction
from flags.models import FlagState

from country_workspace.models import (
    SyncLog,
    Batch,
    Rdp,
    AsyncJob,
    BeneficiaryGroup,
    Program,
    Area,
    AreaType,
    Country,
    Office,
    User,
)


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write("Starting demo data population", self.style.WARNING)

        try:
            self.confirm()
            test_utils_dir = self.get_test_utils_dir()

            with transaction.atomic():
                self.setup_site()
                self.setup_flags()
                self.clean_old_data()
                self.create_base_objects()
                self.sync_data(test_utils_dir)
                self.generate_demo_data()

            self.stdout.write("Finished demo data population", self.style.SUCCESS)

        except CommandError as e:
            self.stdout.write(f"Operation cancelled: {e}", self.style.ERROR)

    def confirm(self) -> bool:
        answer = input("This will DELETE DATA and create demo data. Type 'yes' or 'y' to continue: ").strip().lower()
        if answer not in ("y", "yes"):
            raise CommandError("Operation was not confirmed")

    def get_test_utils_dir(self) -> Path:
        test_utils_dir = Path(__file__).parent.parent.parent.parent.parent / "tests/extras"
        if not test_utils_dir.exists():
            raise CommandError(f"{test_utils_dir.absolute()} does not exist")
        sys.path.append(str(test_utils_dir.absolute()))
        return test_utils_dir

    def setup_site(self) -> None:
        self.stdout.write("Configuring site settings")
        Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={
                "domain": "localhost:8000",
                "name": "localhost",
            },
        )
        Site.objects.clear_cache()

    def setup_flags(self) -> None:
        self.stdout.write("Setting up flags")
        flag_states = [
            FlagState(name=flag, condition="hostname", value="127.0.0.1,localhost") for flag in settings.FLAGS
        ]
        FlagState.objects.bulk_create(flag_states, ignore_conflicts=True)

    def clean_old_data(self) -> None:
        self.stdout.write("Cleaning old data")
        models_to_delete = [AsyncJob, Batch, Rdp, Program, BeneficiaryGroup, Area, AreaType, Office, Country, SyncLog]
        for model in models_to_delete:
            if model.objects.count() > 0:
                model.objects.all().delete()

    def create_base_objects(self) -> None:
        self.stdout.write("Creating group and user")
        Group.objects.get_or_create(name=settings.ANALYST_GROUP_NAME)
        User.objects.get_or_create(username="user")

    def _sync_with_cassette(
        self, cassette_path: Path, record_mode: RecordMode, sync_func: Callable, message: str
    ) -> None:
        self.stdout.write(message)
        vcr_kwargs = {
            "record_mode": record_mode,
            "filter_headers": ["authorization"],
        }
        if record_mode == RecordMode.NONE:
            vcr_kwargs["match_on"] = ("path",)

        try:
            with vcr.use_cassette(cassette_path, **vcr_kwargs):
                sync_func()
        except CannotOverwriteExistingCassetteException:
            if record_mode == RecordMode.NONE:
                self.stdout.write(
                    f"Incomplete cassette: {cassette_path.name}. "
                    f"Some requests missing, continuing with available data...",
                    self.style.WARNING,
                )
            else:
                raise

    def sync_data(self, test_utils_dir: Path) -> None:
        cassettes_dir = test_utils_dir / "cassettes"
        has_token = settings.HOPE_API_TOKEN or config.HOPE_API_TOKEN
        record_mode = RecordMode.ALL if has_token else RecordMode.NONE
        message_suffix = "online" if has_token else "using cassette"

        with transaction.atomic():
            SyncLog.objects.create_lookups()
            self._sync_with_cassette(
                cassettes_dir / "sync_lookups.yaml",
                record_mode,
                SyncLog.objects.refresh,
                f"Syncing lookups {message_suffix}",
            )
            for mode in ("only_context_programs", "only_context_geo"):
                self._sync_with_cassette(
                    cassettes_dir / f"sync_{mode}.yaml",
                    record_mode,
                    lambda mode=mode: call_command("sync", **{mode: True}),
                    f"Syncing {mode} data {message_suffix}",
                )

    def generate_demo_data(self, program_count: int = 5) -> None:
        from testutils.factories import BatchFactory, HouseholdFactory, IndividualFactory

        self.stdout.write("Generating demo data")

        p_filter = {"country_office__active": True, "enabled": True}
        programs = Program.objects.filter(**p_filter).select_related("country_office", "beneficiary_group")
        if not programs:
            raise CommandError("No active programs found")

        for program in programs:
            batch = BatchFactory(country_office=program.country_office, program=program)
            if program.beneficiary_group and program.beneficiary_group.master_detail:
                HouseholdFactory.create_batch(2, batch=batch)
            else:
                IndividualFactory.create_batch(2, batch=batch, household=None)
