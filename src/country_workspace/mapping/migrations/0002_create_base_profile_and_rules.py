from typing import Final
from django.db import migrations
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

PROFILES: Final[dict[str, dict]] = {
    "base": {
        "name": "Base Mapping",
        "description": "Base mapping profile for Excel imports",
        "source_type": "ANY",
        "import_schema": "ANY",
        "is_active": True,
        "parent": None,
        "lft": 1,
        "rght": 2,
        "level": 0,
    },
}

RULES: Final[dict[str, dict]] = {
    "gender_to_sex": {
        "name": "gender_to_sex_mapping",
        "description": "Rename field 'gender' to 'sex'",
        "profile": "base",
        "expression": '{"sex": gender}',
        "order": 10,
    },
    "individual_role": {
        "name": "individual_role_mapping",
        "description": "Define individual collector role (PRIMARY/ALTERNATE/NO_ROLE)",
        "profile": "base",
        "expression": """{"role": household_id && (
            (primary_collector_id && primary_collector_id == household_id) && "PRIMARY" ||
            (alternate_collector_id && alternate_collector_id == household_id) && "ALTERNATE" ||
            "NO_ROLE"
        )}""",
        "order": 100,
    },
}


def create_mapping_profiles_and_rules(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    MappingProfile = apps.get_model("mapping", "MappingProfile")
    FieldMappingRule = apps.get_model("mapping", "FieldMappingRule")

    profiles = {
        key: MappingProfile.objects.get_or_create(
            name=data["name"],
            defaults={
                **data,
                "tree_id": MappingProfile.objects.count() + 1,
            },
        )[0]
        for key, data in PROFILES.items()
    }
    rules = [
        FieldMappingRule(profile=profiles[data["profile"]], **{k: v for k, v in data.items() if k != "profile"})
        for data in RULES.values()
    ]
    FieldMappingRule.objects.bulk_create(rules)


def remove_mapping_profiles_and_rules(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    MappingProfile = apps.get_model("mapping", "MappingProfile")
    FieldMappingRule = apps.get_model("mapping", "FieldMappingRule")

    FieldMappingRule.objects.filter(name__in=[r["name"] for r in RULES.values()]).delete()
    MappingProfile.objects.filter(name__in=[p["name"] for p in PROFILES.values()], rules__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("mapping", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_mapping_profiles_and_rules, remove_mapping_profiles_and_rules),
    ]
