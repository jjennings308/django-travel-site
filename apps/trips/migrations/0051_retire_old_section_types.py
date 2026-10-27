"""Retire phases, callouts, free text and "choose your adventure" sections (retire-old-section-types S2).

1. Any phase, callout or free text left becomes a **note** in place, with a frozen copy of the mapping
   (never import ``day_first`` here: it will change, this must not): a phase's heading → title, summary and
   highlights ("• ") → paragraphs; a callout's tone kept (info → tip), text → paragraphs; free text's
   paragraphs kept; other payload keys kept.
2. A choose-your-adventure section left stops the migration: making "choose one" groups needs the real
   conversion, so run ``manage.py convert_day_first --all --apply`` (S1) first.
3. The field's choices change (no table change).
"""
from django.db import migrations, models

TONES = {"info": "tip", "tip": "tip", "warning": "warning", "critical": "critical"}


def _note(section_type, title, content):
    content = dict(content) if isinstance(content, dict) else {}
    title = title or ""
    if section_type == "phase":
        title = (content.pop("heading", "") or title)[:200]
        paragraphs = [p for p in [content.pop("summary", "")] if p] + [f"• {h}" for h in content.pop("highlights", []) or []]
        tone = ""
    elif section_type == "callout":
        text = content.pop("text", "") or ""
        tone = TONES.get(content.pop("tone", "") or "info", "tip")
        paragraphs = [line for line in text.split("\n") if line.strip()]
    else:
        paragraphs = list(content.pop("paragraphs", []) or [])
        tone = ""
    content.update({"tone": tone, "paragraphs": paragraphs})
    return title, content


def forwards(apps, schema_editor):
    Section = apps.get_model("trips", "Section")
    left = (Section.objects.filter(section_type="choose_your_adventure")
            .values_list("day__trip_id", "day__trip__name").distinct())
    if left:
        trips = "; ".join(f"{name} (trip {pk})" for pk, name in left)
        raise RuntimeError(
            "Choose-your-adventure sections are left, which only the real conversion can turn into "
            f"\"choose one\" groups: run `manage.py convert_day_first --all --apply` first. Trips: {trips}.")
    for section in Section.objects.filter(section_type__in=("phase", "callout", "free_text")):
        section.title, section.content = _note(section.section_type, section.title, section.content)
        section.section_type = "note"
        section.save(update_fields=["title", "content", "section_type"])


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0050_trip_ideas'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='section',
            name='section_type',
            field=models.CharField(choices=[('logistics_table', 'Logistics table'), ('travel', 'Travel'), ('note', 'Note')], max_length=32),
        ),
    ]
