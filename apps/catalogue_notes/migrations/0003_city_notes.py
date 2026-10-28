"""Notes on cities too: a fourth target, and the one-target rule widened to it."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalogue_notes', '0002_approval_queue'),
        ('locations', '0016_country_flag_media'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='cataloguenote',
            name='catalogue_note_one_target',
        ),
        migrations.AddField(
            model_name='cataloguenote',
            name='city',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='catalogue_notes', to='locations.city'),
        ),
        migrations.AddConstraint(
            model_name='cataloguenote',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('activity__isnull', True), ('city__isnull', True), ('event__isnull', True), ('poi__isnull', False)), models.Q(('activity__isnull', False), ('city__isnull', True), ('event__isnull', True), ('poi__isnull', True)), models.Q(('activity__isnull', True), ('city__isnull', True), ('event__isnull', False), ('poi__isnull', True)), models.Q(('activity__isnull', True), ('city__isnull', False), ('event__isnull', True), ('poi__isnull', True)), _connector='OR'), name='catalogue_note_one_target'),
        ),
    ]
