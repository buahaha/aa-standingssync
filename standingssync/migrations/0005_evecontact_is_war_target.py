# Generated by Django 3.1.4 on 2021-01-11 21:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("standingssync", "0004_simplify_contacts"),
    ]

    operations = [
        migrations.AddField(
            model_name="evecontact",
            name="is_war_target",
            field=models.BooleanField(default=False),
            preserve_default=False,
        ),
    ]