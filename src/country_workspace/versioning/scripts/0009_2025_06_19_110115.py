from packaging.version import Version
from country_workspace.models import FieldMappingRule, MappingProfile

_script_for_version = Version("0.1.0")

PROFILES = {
    "base": {
        "name": "Base Mapping",
        "description": "Base mapping profile for Excel imports",
        "source_type": MappingProfile.SourceType.ANY,
        "import_schema": MappingProfile.ImportSchema.ANY,
        "is_active": True,
        "parent": None,
    },
}

RULES = {
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


def forward() -> None:
    profiles = {
        key: MappingProfile.objects.get_or_create(name=data["name"], defaults=data)[0] for key, data in PROFILES.items()
    }
    rules = [
        FieldMappingRule(profile=profiles[data["profile"]], **{k: v for k, v in data.items() if k != "profile"})
        for data in RULES.values()
    ]
    FieldMappingRule.objects.bulk_create(rules)


def backward() -> None:
    FieldMappingRule.objects.filter(name__in=[r["name"] for r in RULES.values()]).delete()
    MappingProfile.objects.filter(name__in=[p["name"] for p in PROFILES.values()], rules__isnull=True).delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
