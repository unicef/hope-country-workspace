from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0030_alter_synclog_name"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="individual",
            options={
                "permissions": (
                    ("validate_beneficiary", "Can validate Beneficiary Records"),
                    ("mass_update_beneficiary", "Can Mass update Beneficiary Records"),
                    ("regex_update_beneficiary", "Can Mass update Beneficiary Records"),
                    ("export_beneficiary", "Can Export Beneficiary Records"),
                    ("push_beneficiary_to_hope", "Can Push Beneficiary Records To HOPE core"),
                    ("name_parser_beneficiary", "Can Parse Name into Components"),
                )
            },
        ),
    ]
