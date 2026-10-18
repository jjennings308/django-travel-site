# Site roadmap R11: one membership model. Copy each rewards.UserRewardsMembership (per account)
# onto that account's Traveler as a trips.RewardsMembership, before rewards drops the old model.
#
# ``run_before`` puts the ordering here, in trips (the higher layer), so rewards' own migration
# history never depends on trips. A traveller who already has that program keeps theirs, with
# anything new (number, tier, expiry) filled in where it was blank; "the same program" is the
# catalogue link, the exact name, "company name", or a typed name containing the program's name. Points, username and member
# name have no field here, so they go into notes. Reversible: the copied rows are removed again
# (the old rows themselves are only gone once rewards' migration has run).
from django.db import migrations

KIND = {"airline": "airline", "hotel": "hotel", "car_rental": "car_rental", "credit_card": "credit_card",
        "train": "rail", "cruise": "other", "other": "other"}
MARK = "[copied from the rewards page]"


def full_name(program):
    """ "Delta SkyMiles" for the catalogue's company Delta, program SkyMiles (how people type it)."""
    if program.company and program.company.lower() not in program.name.lower():
        return f"{program.company} {program.name}"
    return program.name


def copy(apps, schema_editor):
    Old = apps.get_model("rewards", "UserRewardsMembership")
    New = apps.get_model("trips", "RewardsMembership")
    Traveler = apps.get_model("trips", "Traveler")
    for old in Old.objects.select_related("program").order_by("pk"):
        traveler = Traveler.objects.filter(user_id=old.user_id).order_by("pk").first()
        if traveler is None:
            continue  # an account with no traveller row (the signal links one on the next save)
        program = old.program
        extra = [f"Points: {old.points_balance}" if old.points_balance else "",
                 f"Username: {old.username}" if old.username else "",
                 f"Name on the account: {old.member_name}" if old.member_name else "",
                 f"Full member number: {old.member_number}" if len(old.member_number) > 40 else "",
                 old.notes or ""]
        notes = "\n".join(line for line in extra if line)
        existing = (New.objects.filter(traveler=traveler, catalogue_program=program).first()
                    or New.objects.filter(traveler=traveler, program__iexact=program.name).first()
                    or New.objects.filter(traveler=traveler, program__iexact=full_name(program)).first()
                    # "Delta SkyMiles" typed on the profile is the catalogue's "SkyMiles" (Delta Air Lines).
                    or (New.objects.filter(traveler=traveler, program__icontains=program.name).first()
                        if len(program.name) >= 4 else None))
        if existing:
            changed = []
            for field, value in (("member_number", old.member_number[:40]), ("tier", (old.current_tier or "")[:60]),
                                 ("expires", old.tier_expires)):
                if value and not getattr(existing, field):
                    setattr(existing, field, value)
                    changed.append(field)
            if existing.catalogue_program_id is None:
                existing.catalogue_program = program
                changed.append("catalogue_program")
            if notes and notes not in existing.notes:
                existing.notes = "\n".join(filter(None, [existing.notes, notes]))
                changed.append("notes")
            if changed:
                existing.save(update_fields=changed)
            continue
        New.objects.create(
            traveler=traveler, catalogue_program=program, program=full_name(program)[:120],
            kind=KIND.get(program.program_type, "other"), member_number=old.member_number[:40],
            tier=(old.current_tier or "")[:60], expires=old.tier_expires,
            notes="\n".join(filter(None, [notes, MARK])))


def uncopy(apps, schema_editor):
    New = apps.get_model("trips", "RewardsMembership")
    New.objects.filter(notes__contains=MARK).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0041_membership_catalogue_program"),
        ("rewards", "0002_remove_rewardsprogram_rewards_program_unique_name_company_and_more"),
    ]
    run_before = [("rewards", "0003_delete_userrewardsmembership")]
    operations = [migrations.RunPython(copy, uncopy)]
