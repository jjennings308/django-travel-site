# Confirmations attach to items like comments do (generic links). Schema only: the copy of
# the old legs/stays/meals links is 0027 and the drop is 0028, kept apart because Postgres
# refuses index work after a data change in the same transaction.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('trips', '0025_booking_task_items'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfirmationLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.PositiveBigIntegerField()),
                ('confirmation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='links', to='trips.confirmation')),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype')),
            ],
            options={
                'indexes': [models.Index(fields=['content_type', 'object_id'], name='trips_confi_content_e973c0_idx')],
                'constraints': [models.UniqueConstraint(fields=('confirmation', 'content_type', 'object_id'), name='confirmationlink_once_per_item')],
            },
        ),
    ]
