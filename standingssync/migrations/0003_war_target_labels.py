# Generated by Django 3.1.5 on 2021-01-24 18:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("standingssync", "0002_add_war_targets"),
    ]

    operations = [
        migrations.AddField(
            model_name="syncedcharacter",
            name="has_war_targets_label",
            field=models.BooleanField(default=None, null=True),
        ),
    ]
