# Generated by Django 2.2.5 on 2019-09-19 11:55

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    
    initial = True

    dependencies = [
        ('eveonline', '0010_alliance_ticker'),
        ('authentication', '0016_ownershiprecord'),
    ]

    operations = [
        migrations.CreateModel(
            name='SyncManager',
            fields=[
                ('alliance', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False, to='eveonline.EveAllianceInfo')),
                ('version_hash', models.CharField(default=None, max_length=32, null=True)),
                ('last_sync', models.DateTimeField(default=None, null=True)),
                ('character', models.OneToOneField(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='authentication.CharacterOwnership')),
            ],
        ),
        migrations.CreateModel(
            name='SyncedCharacter',
            fields=[
                ('character', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False, to='authentication.CharacterOwnership')),
                ('version_hash', models.CharField(default=None, max_length=32, null=True)),
                ('last_error', models.IntegerField(choices=[(0, 'No error'), (1, 'Invalid token'), (99, 'Unknown error')], default=0)),
                ('last_sync', models.DateTimeField(default=None, null=True)),
                ('manager', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='standingssync.SyncManager')),
            ],
        ),
        migrations.CreateModel(
            name='AllianceContact',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contact_id', models.IntegerField()),
                ('contact_type', models.CharField(max_length=32)),
                ('standing', models.FloatField()),
                ('manager', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='standingssync.SyncManager')),
            ],
        ),
        migrations.AddConstraint(
            model_name='alliancecontact',
            constraint=models.UniqueConstraint(fields=('manager', 'contact_id'), name='manager-contacts-unq'),
        ),
        migrations.AlterField(
            model_name='syncedcharacter',
            name='last_error',
            field=models.IntegerField(choices=[(0, 'No error'), (1, 'Invalid token'), (2, 'Insufficient permissions'), (99, 'Unknown error')], default=0),
        ),
        migrations.AlterField(
            model_name='syncedcharacter',
            name='last_error',
            field=models.IntegerField(choices=[(0, 'No error'), (1, 'Invalid token'), (2, 'Expired token'), (3, 'Insufficient permissions'), (5, 'ESI API is currently unavailable'), (99, 'Unknown error')], default=0),
        ),
        migrations.AddField(
            model_name='syncmanager',
            name='last_error',
            field=models.IntegerField(choices=[(0, 'No error'), (1, 'Invalid token'), (2, 'Expired token'), (3, 'Insufficient permissions'), (4, 'No character set for fetching alliance contacts'), (5, 'ESI API is currently unavailable'), (99, 'Unknown error')], default=0),
        ),
    ]