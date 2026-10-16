# Copy each confirmation's legs / stays / meals (the Phase B many-to-many tables) into
# ConfirmationLink rows. Reversible: the reverse copies the links back.
from django.db import migrations

KINDS = (("legs", "transportleg"), ("stays", "lodging"), ("meals", "meal"))


def _content_type(apps, model):
    ContentType = apps.get_model("contenttypes", "ContentType")
    return ContentType.objects.get_or_create(app_label="trips", model=model)[0]


def copy_links(apps, schema_editor=None):
    Confirmation = apps.get_model("trips", "Confirmation")
    ConfirmationLink = apps.get_model("trips", "ConfirmationLink")
    for field, model in KINDS:
        content_type = _content_type(apps, model)
        through = getattr(Confirmation, field).through
        column = f"{model}_id"
        rows = [ConfirmationLink(confirmation_id=row.confirmation_id, content_type=content_type,
                                 object_id=getattr(row, column))
                for row in through.objects.all()]
        ConfirmationLink.objects.bulk_create(rows, ignore_conflicts=True)


def copy_back(apps, schema_editor=None):
    Confirmation = apps.get_model("trips", "Confirmation")
    ConfirmationLink = apps.get_model("trips", "ConfirmationLink")
    for field, model in KINDS:
        content_type = _content_type(apps, model)
        through = getattr(Confirmation, field).through
        column = f"{model}_id"
        through.objects.bulk_create(
            [through(confirmation_id=link.confirmation_id, **{column: link.object_id})
             for link in ConfirmationLink.objects.filter(content_type=content_type)],
            ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0026_confirmation_link'),
    ]

    operations = [
        migrations.RunPython(copy_links, copy_back),
    ]
