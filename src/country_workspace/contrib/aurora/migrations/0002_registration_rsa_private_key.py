from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aurora", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="registration",
            name="rsa_private_key",
            field=models.TextField(
                blank=True,
                default="",
                help_text=(
                    "RSA private key (PEM) used to decrypt records imported from Aurora when encryption is enabled."
                ),
            ),
        ),
    ]
