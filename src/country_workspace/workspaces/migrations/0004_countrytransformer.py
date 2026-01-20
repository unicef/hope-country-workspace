# Generated migration for CountryTransformer proxy model

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0041_create_transformer_and_migrate_data"),
        ("workspaces", "0003_countrymappingimporter"),
    ]

    operations = [
        migrations.CreateModel(
            name="CountryTransformer",
            fields=[],
            options={
                "verbose_name": "Transformer",
                "verbose_name_plural": "Transformers",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("country_workspace.transformer",),
        ),
    ]
