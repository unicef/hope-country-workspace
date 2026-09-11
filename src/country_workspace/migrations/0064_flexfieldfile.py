import uuid

import django.db.models.deletion
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("country_workspace", "0063_alter_rdp_country_office_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="FlexFieldFile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("object_id", models.PositiveIntegerField()),
                ("field_name", models.CharField(max_length=255, verbose_name="Field name")),
                ("content", models.BinaryField(verbose_name="Content")),
                ("mimetype", models.CharField(max_length=100, verbose_name="Mimetype")),
                ("size", models.PositiveIntegerField(default=0, verbose_name="Size")),
                ("original_filename", models.CharField(blank=True, max_length=255, verbose_name="Original filename")),
                ("checksum", models.CharField(db_index=True, max_length=64, verbose_name="Checksum")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "verbose_name": "Flex Field File",
                "verbose_name_plural": "Flex Field Files",
            },
        ),
        AddIndexConcurrently(
            model_name="flexfieldfile",
            index=models.Index(
                fields=["content_type", "object_id", "field_name"],
                name="cw_flexfile_owner_field_idx",
            ),
        ),
    ]
