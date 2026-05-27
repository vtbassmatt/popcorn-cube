from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cubes", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="submission",
            name="card_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
