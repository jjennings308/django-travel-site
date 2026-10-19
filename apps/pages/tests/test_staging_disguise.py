"""The disguise applied to staging's copy of production (site roadmap R16; scripts/staging_disguise.sql).
In pages because it touches accounts and trips tables."""
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
User = get_user_model()


class DisguiseTests(TestCase):
    def test_no_real_email_phone_or_document_number_survives(self):
        from apps.trips.models import Contact, Traveler, Trip, TripInvite
        ada = User.objects.create_user("ada", "ada@real.example", "pw-1234-abcd", phone_number="+1 555 0100")
        traveler = Traveler.objects.get(user=ada)
        Traveler.objects.filter(pk=traveler.pk).update(passport_number="X1234567", known_traveler_number="KTN1",
                                                        redress_number="R1")
        trip = Trip.objects.create(name="Rome", start_date=date(2027, 5, 1), end_date=date(2027, 5, 2))
        Contact.objects.create(trip=trip, name="Hotel", email="desk@hotel.example", phone="+39 06 1")
        TripInvite.objects.create(trip=trip, email="friend@real.example")
        sql = (SCRIPTS / "staging_disguise.sql").read_text()
        statements = [s.strip() for s in sql.split(";") if s.strip()
                      and not s.strip().upper().endswith(("BEGIN", "COMMIT"))]
        with connection.cursor() as cursor:
            for statement in statements:
                lines = [line for line in statement.splitlines() if not line.strip().startswith("--")]
                if "".join(lines).strip():
                    cursor.execute("\n".join(lines))
            cursor.execute("SELECT count(*) FROM users WHERE email NOT LIKE '%%@staging.invalid'")
            self.assertEqual(cursor.fetchone()[0], 0)
        ada.refresh_from_db()
        self.assertEqual((ada.email, ada.phone_number), (f"user{ada.pk}@staging.invalid", ""))
        traveler.refresh_from_db()
        self.assertEqual((traveler.passport_number, traveler.known_traveler_number, traveler.redress_number), ("", "", ""))
        self.assertTrue(Contact.objects.get().email.endswith("@staging.invalid"))
        self.assertEqual(Contact.objects.get().phone, "+39 06 1")  # businesses' numbers stay
        self.assertTrue(TripInvite.objects.get().email.endswith("@staging.invalid"))
