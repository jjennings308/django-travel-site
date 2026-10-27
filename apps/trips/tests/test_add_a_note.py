"""Starting a note on a day, a plan section or a task from the trip page (before, only the trip
itself had an "Add a comment" until something already had a note)."""
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import BookingTask, Comment, Day, Section, Trip, TripGrant, TripRole

User = get_user_model()


class AddANoteTests(TestCase):
    def setUp(self):
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 20), end_date=date(2027, 9, 21))
        self.users = {}
        for role in (TripRole.VIEWER, TripRole.COMMENTOR, TripRole.EDITOR):
            user = User.objects.create_user(role, f"{role}@example.com", "pw-1234-abcd")
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
            self.users[role] = user
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))
        self.section = Section.objects.create(day=self.day, section_type="note", title="Afternoon",
                                              content={"paragraphs": ["Stroll."]})
        self.task = BookingTask.objects.create(trip=self.trip, title="ICE seats")
        self.links = [reverse("trips:comment_create", args=[kind, pk])
                      for kind, pk in (("day", self.day.pk), ("section", self.section.pk), ("task", self.task.pk))]

    def page(self, role):
        self.client.force_login(self.users[role])
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()

    def test_links_for_commentors_and_editors_not_viewers(self):
        for role in (TripRole.COMMENTOR, TripRole.EDITOR):
            html = self.page(role)
            self.assertIn("Add a note to this day", html)
            for link in self.links:
                self.assertIn(link, html)
        html = self.page(TripRole.VIEWER)
        for link in self.links:
            self.assertNotIn(link, html)

    def test_a_note_lands_back_on_its_day_and_the_thread_takes_over(self):
        self.client.force_login(self.users[TripRole.COMMENTOR])
        response = self.client.post(self.links[0], {"body": "Bring cash for the castle."})
        comment = Comment.objects.get()
        location = response["Location"]
        self.assertEqual(location, reverse("trips:trip_detail", args=[self.trip.pk]) + f"#comment-{comment.pk}")
        html = self.page(TripRole.COMMENTOR)
        self.assertIn(f'id="comment-{comment.pk}"', html)
        self.assertIn("Notes on this day", html)
        self.assertNotIn("Add a note to this day", html)  # its thread's Add a comment takes over
        day_html = html[html.index('id="day-1"'):html.index('id="reference"')]
        self.assertIn(f'id="comment-{comment.pk}"', day_html)  # inside the day, so the page opens it
