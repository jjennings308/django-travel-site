"""The zone chosen in Settings is the one pages use (UserTimezoneMiddleware; fixed in site roadmap R21 —
it used to read the deprecated UserPreferences, so everyone was UTC)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import AccountSettings
from apps.core.middleware import UserTimezoneMiddleware

User = get_user_model()


class UserTimezoneTests(TestCase):
    def zone_for(self, user):
        seen = {}

        def view(request):
            seen["zone"] = timezone.get_current_timezone_name()
            return None
        request = RequestFactory().get("/")
        request.user = user
        UserTimezoneMiddleware(view)(request)
        return seen["zone"]

    def test_settings_zone_is_used(self):
        user = User.objects.create_user("tz", "tz@example.com", "pw-1234-abcd")
        AccountSettings.objects.update_or_create(user=user, defaults={"timezone": "America/New_York"})
        self.assertEqual(self.zone_for(User.objects.get(pk=user.pk)), "America/New_York")

    def test_missing_or_bad_zone_and_signed_out_are_utc(self):
        user = User.objects.create_user("tz2", "tz2@example.com", "pw-1234-abcd")
        AccountSettings.objects.filter(user=user).delete()
        self.assertEqual(self.zone_for(User.objects.get(pk=user.pk)), "UTC")
        AccountSettings.objects.create(user=user, timezone="Not/AZone")
        self.assertEqual(self.zone_for(User.objects.get(pk=user.pk)), "UTC")
        self.assertEqual(self.zone_for(AnonymousUser()), "UTC")
