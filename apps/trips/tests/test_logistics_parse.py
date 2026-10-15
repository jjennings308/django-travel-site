"""apps.trips.logistics: travel rows of a logistics table, as written in the Europe draft."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.trips.logistics import match_city, proposed_legs


class ParseTests(SimpleTestCase):
    def test_leg_table(self):
        legs = proposed_legs(
            ["Transport Leg", "Train", "Time", "Notes"],
            [["Butzbach → Frankfurt Hbf", "RE30 / Mittelhessen-Express", "~45 min", "Frequent service throughout the day"],
             ["Frankfurt Hbf → Augsburg Hbf", "ICE direct", "~2.5 hrs", "Book advance fares"],
             ["Total journey", "—", "~3.5 hrs", "Arrive Augsburg mid-afternoon comfortably"]])
        self.assertEqual(len(legs), 2)  # "Total journey" skipped
        self.assertEqual(legs[0], {"row": 0, "origin": "Butzbach", "destination": "Frankfurt Hbf", "mode": "train",
                                   "operator": "RE30 / Mittelhessen-Express",
                                   "notes": "~45 min · Frequent service throughout the day"})

    def test_prose_row_ends_the_place_at_the_comma(self):
        legs = proposed_legs(["Detail", "Info"],
                             [["Departure", "Augsburg Hbf → München Hbf, mid-morning (~10–10:30am). No early alarm."]])
        self.assertEqual((legs[0]["origin"], legs[0]["destination"]), ("Augsburg Hbf", "München Hbf"))
        self.assertIn("mid-morning", legs[0]["notes"])

    def test_non_travel_table_gives_nothing(self):
        self.assertEqual(proposed_legs(["Detail", "Info"], [["Car type", "Compact"], ["Transmission", "Automatic"]]), [])

    def test_modes(self):
        rows = [["A → B", "Lufthansa flight"], ["C → D", "Rental car from Avis"], ["E → F", "Walk along the river"],
                ["G → H", "Bus"]]
        self.assertEqual([leg["mode"] for leg in proposed_legs(["Leg", "Notes"], rows)],
                         ["plane", "rental_car", "walking", "other"])

    def test_match_city(self):
        cities = [SimpleNamespace(name=n) for n in ("Frankfurt", "Augsburg", "York", "New York")]
        self.assertEqual(match_city("Frankfurt Hbf", cities).name, "Frankfurt")
        self.assertEqual(match_city("New York Penn", cities).name, "New York")
        self.assertIsNone(match_city("München Hbf", cities))
