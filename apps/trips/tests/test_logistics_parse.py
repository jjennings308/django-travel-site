"""apps.trips.logistics: travel rows of a logistics table, as written in the Europe draft."""
from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.trips.logistics import match_city, proposed_legs, total_notes


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
                                   "notes": "Frequent service throughout the day",  # the time is the duration
                                   "duration": timedelta(minutes=45), "strength": "arrow"})

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

    def test_strength_verbs_and_durations(self):
        """Taos's day schedules: "Via …" and "to" rows are only possible; "Depart ABQ → SLC" is ABQ → SLC."""
        legs = proposed_legs(["Time", "Stop", "Details"], [
            ["~10:15 AM", "Depart Santa Fe", "Via Hwy 503 → Hwy 76 (High Road)"],
            ["~3:00 PM", "Continue to Angel Fire", "Via Taos, then east ~30–40 min"],
            ["6:10 PM", "Depart ABQ → SLC", "DL 3726"]])
        self.assertEqual([leg["strength"] for leg in legs], ["possible", "possible", "arrow"])
        self.assertEqual((legs[2]["origin"], legs[2]["destination"], legs[2]["duration"]), ("ABQ", "SLC", None))
        self.assertEqual(legs[1]["duration"], timedelta(minutes=40))  # first rough time in the prose
        bayern = proposed_legs(["Detail", "Info"], [["München Hbf → Theresienwiese", "U4 or U5 — 2 stops, ~5 min."]])
        self.assertEqual(bayern[0]["duration"], timedelta(minutes=5))

    def test_total_notes(self):
        self.assertEqual(total_notes(["Leg", "Mode", "Time", "Notes"], [
            ["A → B", "S8", "~40 min", ""],
            ["Total Augsburg → MUC", "—", "~1 hr 15 min", "Allow 2.5 hrs at MUC"],
            ["Total journey", "—", "~3 hrs", ""]]),
            [{"row": 1, "note": "Allow 2.5 hrs at MUC"}, {"row": 2, "note": ""}])
