# Generated by Django 5.0.6 on 2024-07-05 14:28

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hope_country_workspace", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="household",
            options={"verbose_name": "Household"},
        ),
        migrations.RemoveField(
            model_name="household",
            name="address",
        ),
        migrations.RemoveField(
            model_name="household",
            name="admin1",
        ),
        migrations.RemoveField(
            model_name="household",
            name="admin2",
        ),
        migrations.RemoveField(
            model_name="household",
            name="admin3",
        ),
        migrations.RemoveField(
            model_name="household",
            name="admin4",
        ),
        migrations.RemoveField(
            model_name="household",
            name="admin_area",
        ),
        migrations.RemoveField(
            model_name="household",
            name="children_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="children_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="country",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_0_5_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_0_5_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_12_17_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_12_17_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_18_59_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_18_59_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_60_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_60_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_6_11_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_age_group_6_11_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_children_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="female_children_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_0_5_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_0_5_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_12_17_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_12_17_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_18_59_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_18_59_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_60_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_60_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_6_11_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_age_group_6_11_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_children_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="male_children_disabled_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="pregnant_count",
        ),
        migrations.RemoveField(
            model_name="household",
            name="representatives",
        ),
        migrations.RemoveField(
            model_name="household",
            name="residence_status",
        ),
        migrations.RemoveField(
            model_name="household",
            name="size",
        ),
        migrations.RemoveField(
            model_name="household",
            name="zip_code",
        ),
    ]
