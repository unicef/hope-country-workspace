# Generated by Django 5.1.1 on 2024-10-15 16:45

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Version",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, unique=True)),
                ("version", models.CharField(max_length=255)),
                ("applied", models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
    ]