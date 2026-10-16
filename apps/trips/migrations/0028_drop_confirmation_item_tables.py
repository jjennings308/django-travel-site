# The Phase B many-to-many tables, now copied into ConfirmationLink (0027).
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0027_copy_confirmation_links'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='confirmation',
            name='legs',
        ),
        migrations.RemoveField(
            model_name='confirmation',
            name='meals',
        ),
        migrations.RemoveField(
            model_name='confirmation',
            name='stays',
        ),
    ]
