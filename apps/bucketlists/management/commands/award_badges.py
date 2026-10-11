"""Award every badge users have already earned (e.g. after badges were added).

    python manage.py award_badges            # silent: no notifications
    python manage.py award_badges --notify   # also notify each new badge
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.bucketlists.badges import award_badges


class Command(BaseCommand):
    help = "Record badges users have already earned (silently unless --notify)."

    def add_arguments(self, parser):
        parser.add_argument("--notify", action="store_true", help="Send a notification for each new badge.")

    def handle(self, *args, notify=False, **options):
        total = 0
        for user in get_user_model().objects.filter(is_active=True, bucket_list_items__isnull=False).distinct():
            new = award_badges(user, notify=notify)
            if new:
                total += len(new)
                self.stdout.write(f"{user.username}: {', '.join(b.title for b in new)}")
        self.stdout.write(f"{total} badge(s) awarded.")
