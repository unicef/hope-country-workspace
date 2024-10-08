import logging
import sys
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import BaseCommand
from django.utils.text import slugify

from hope_flex_fields.models import DataChecker

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> None:
        from django.contrib.sites.models import Site

        from flags.models import FlagState

        from country_workspace.models import Office, User

        Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={
                "domain": "localhost:8000",
                "name": "localhost",
            },
        )
        Site.objects.clear_cache()

        for flag in settings.FLAGS.keys():
            FlagState.objects.get_or_create(
                name=flag, condition="hostname", value="127.0.0.1,localhost"
            )

        Office.objects.get_or_create(
            slug=slugify(
                settings.TENANT_HQ,
            ),
            name=settings.TENANT_HQ,
        )

        analysts, __ = Group.objects.get_or_create(name=settings.ANALYST_GROUP_NAME)
        user, __ = User.objects.get_or_create(username="user")

        # Create HH Validator
        from django import forms

        from hope_flex_fields.models import FieldDefinition, Fieldset, FlexField

        bool_field = FieldDefinition.objects.get(name="BooleanField")
        char_field = FieldDefinition.objects.get(name="CharField")
        date_field = FieldDefinition.objects.get(field_type=forms.DateField)
        # choice_field = FieldDefinition.objects.get(
        #     name="ChoiceField", field_type=forms.ChoiceField
        # )
        gender_field, __ = FieldDefinition.objects.get_or_create(
            name="Gender",
            attrs={"choices": [["FEMALE", "FEMALE"], ["MALE", "MALE"]]},
            field_type=forms.ChoiceField,
        )

        hh_fs, __ = Fieldset.objects.get_or_create(name="household")
        FlexField.objects.get_or_create(
            name="household_id", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="consent_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="country_origin_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="country_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="admin1_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="admin2_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="size_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="hh_latrine_h_f", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="hh_electricity_h_f", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="registration_method_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="collect_individual_data_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="name_enumerator_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="org_enumerator_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="consent_sharing_h_c", fieldset=hh_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="first_registration_date_h_c", fieldset=hh_fs, field=char_field
        )

        ind_fs, __ = Fieldset.objects.get_or_create(name="individual")
        FlexField.objects.get_or_create(
            name="household_id", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="relationship_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="full_name_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="given_name_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="middle_name_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="family_name_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="photo_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="gender_i_c", fieldset=ind_fs, field=gender_field
        )

        FlexField.objects.get_or_create(
            name="birth_date_i_c", fieldset=ind_fs, field=date_field
        )
        FlexField.objects.get_or_create(
            name="estimated_birth_date_i_c", fieldset=ind_fs, field=bool_field
        )
        FlexField.objects.get_or_create(
            name="national_id_no_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="national_id_photo_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="national_id_issuer_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="phone_no_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="primary_collector_id", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="alternate_collector_id", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="first_registration_date_i_c", fieldset=ind_fs, field=char_field
        )
        FlexField.objects.get_or_create(
            name="disability_i_c",
            fieldset=ind_fs,
            field=FieldDefinition.objects.get(name="ChoiceField"),
            attrs={
                "choices": [["not disabled", "not disabled"], ["disabled", "disabled"]]
            },
        )

        ds, __ = DataChecker.objects.get_or_create(name="Base Household")
        ds.fieldsets.add(hh_fs)
        ds, __ = DataChecker.objects.get_or_create(name="Base Individual")
        ds.fieldsets.add(ind_fs)

        test_utils_dir = (
            Path(__file__).parent.parent.parent.parent.parent / "tests/extras"
        )
        assert test_utils_dir.exists(), (
            str(test_utils_dir.absolute()) + " does not exist"
        )
        sys.path.append(str(test_utils_dir.absolute()))
        import vcr
        from testutils.factories import HouseholdFactory
        from vcr.record_mode import RecordMode

        from country_workspace.sync.office import sync_all

        with vcr.use_cassette(
            test_utils_dir.parent / "sync_all.yaml",
            record_mode=RecordMode.NONE,
        ):
            sync_all()

        for co in Office.objects.filter(active=True):
            for p in co.programs.filter():
                HouseholdFactory.create_batch(10, country_office=co, program=p)