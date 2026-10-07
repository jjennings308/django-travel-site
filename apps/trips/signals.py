"""Keep ``Traveler`` and the auth user in step.

The rule is one-way: **every account is a traveler, but not every traveler
has an account.** Saving an account therefore links the traveler row that
already carries that person's trips and notes, or creates one if the roster
does not know them yet. Saving a traveler links it to a matching account if
one exists, and does nothing when none does — an accountless traveler is the
normal case, not a gap to fill.

Both directions match on the exact name (``first_name last_name``, falling
back to the username) and only when the answer is unique: two rows called the
same thing means the roster needs ``dedupe_travelers``, and guessing which
row is the person would attach someone's login to a stranger's trips. Links
are written with a queryset ``update()`` so neither receiver can re-enter the
other.
"""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Traveler

User = get_user_model()


def display_name(user):
    """The name a traveler row for this account would carry."""
    return user.get_full_name() or user.username


@receiver(post_save, sender=User)
def ensure_traveler_for_user(sender, instance, **kwargs):
    """Every account is a traveler: link the right row, or make one."""
    if Traveler.objects.filter(user_id=instance.pk).exists():
        return
    matches = list(
        Traveler.objects.filter(name=display_name(instance), user=None)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if len(matches) == 1:
        Traveler.objects.filter(pk=matches[0], user=None).update(user=instance)
    elif not matches:
        Traveler.objects.create(name=display_name(instance), user=instance)
    # Several rows share the name: leave the account unlinked rather than
    # guess. The account still works; only the traveler link is deferred.


@receiver(post_save, sender=Traveler)
def link_traveler_to_account(sender, instance, **kwargs):
    """A traveler whose name matches an unclaimed account is linked to it."""
    if instance.user_id:
        return
    claimed = set(
        Traveler.objects.exclude(user=None).values_list("user_id", flat=True)
    )
    candidates = [
        user
        for user in User.objects.all()
        if user.pk not in claimed and display_name(user) == instance.name
    ]
    if len(candidates) == 1:
        linked = Traveler.objects.filter(pk=instance.pk, user=None).update(
            user=candidates[0]
        )
        if linked:
            # Keep the saved instance truthful: the queryset update above
            # never touches it, and the creator's object must not read back
            # as unlinked moments after the link was made.
            instance.user_id = candidates[0].pk
    # Zero candidates is the ordinary case; several means two accounts answer
    # to one name and need an administrator to say which is which.
