"""Goals already on a trip become ideas on its shelf (day-first plan P6).

Each goal with a trip and no idea gets one on that trip (unplaced, so it shows on the trip's Ideas shelf),
copying its catalogue target — its event, else its activity, city or first place — and never its
personal notes; two goals about the same thing on one trip share an idea. The goal's owner votes for it,
as linking a goal does from now on. Hand-written and separate from 0007 (Postgres refuses index creation
after a data change in one transaction).
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Item = apps.get_model("bucketlists", "BucketListItem")
    TripIdea = apps.get_model("trips", "TripIdea")
    Vote = apps.get_model("trips", "Vote")
    goals = (Item.objects.filter(trip__isnull=False, trip_idea__isnull=True)
             .select_related("activity", "city", "event").prefetch_related("pois"))
    for goal in goals:
        field, target = None, None
        for name in ("event", "activity", "city"):
            if getattr(goal, f"{name}_id"):
                field, target = name, getattr(goal, name)
                break
        else:
            pois = sorted(goal.pois.all(), key=lambda p: p.name)
            if pois:
                field, target = "poi", pois[0]
        idea = TripIdea.objects.filter(trip_id=goal.trip_id, **{field: target}).first() if field else None
        if idea is None:
            title = goal.custom_title or (target.name if target is not None else "") or "A goal"
            idea = TripIdea.objects.create(trip_id=goal.trip_id, title=title[:200], added_by_id=goal.user_id,
                                           **({field: target} if field else {}))
        Vote.objects.get_or_create(user_id=goal.user_id, idea=idea)
        Item.objects.filter(pk=goal.pk).update(trip_idea=idea)


class Migration(migrations.Migration):

    dependencies = [
        ("bucketlists", "0007_goal_trip_idea"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
