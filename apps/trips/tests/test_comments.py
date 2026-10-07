"""Tests for comments.

Three things are worth pinning, and the middle one is the reason comments are
harder to get right than they look.

The first is access. A comment inherits its parent's trip rather than storing
who can see it, so the test is that a user with no grant cannot read *or* post,
and that a 404 — not a 403 — is what they get, since the existence of someone
else's comment is itself information.

The second is that the target cannot be forged. The form has one field, `body`;
`content_type` and `object_id` come from the URL. If either were form data, a
hand-written POST could attach a comment to a trip the poster cannot see — and it
would then be readable by anyone who *can* see that trip. So a post naming a
foreign trip is a 404.

The third is the orphan. A `GenericForeignKey` has no cascading delete, so a
comment whose target is deleted survives as a row pointing at nothing. It must
not be reachable by anyone, and it must not take the target's page down with it.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import TripRole
from apps.trips.models import Comment, Day, Section, Trip, TripGrant

User = get_user_model()


def make_user(username, **kwargs):
    return User.objects.create_user(
        username, f"{username}@example.com", "pw-1234-abcd", **kwargs
    )


class CommentFixture(TestCase):
    def setUp(self):
        self.staff = make_user("root", is_staff=True, is_superuser=True)

        # ada can read, bob has no grant, cara has no role at all.
        self.ada = make_user("ada")
        self.bob = make_user("bob")
        self.cara = make_user("cara")

        self.trip = Trip.objects.create(
            name="Europe 2027",
            start_date=date(2027, 9, 25),
            end_date=date(2027, 10, 5),
        )
        self.day = Day.objects.create(
            trip=self.trip, day_number=1, date=date(2027, 9, 25), theme="Fly out"
        )
        self.section = Section.objects.create(
            day=self.day,
            section_type=Section.Type.CALLOUT,
            title="Bring a jumper",
            content={"tone": "info", "text": "It is cold up there."},
        )

        # cara holds no grant, so she cannot reach the trip at all.
        TripGrant.objects.create(
            trip=self.trip, user=self.ada, role=TripRole.COMMENTOR, granted_by=self.staff
        )
        TripGrant.objects.create(
            trip=self.trip, user=self.bob, role=TripRole.COMMENTOR, granted_by=self.staff
        )

    def login(self, user):
        self.client.force_login(user)


class CommentAccessTests(CommentFixture):
    """Who can post, read and reach a comment."""

    def test_a_commentor_with_a_grant_can_post(self):
        self.login(self.ada)
        response = self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "Can we push the hike to day 3?"},
        )
        self.assertEqual(response.status_code, 302)
        comment = Comment.objects.get()
        self.assertEqual(comment.author, self.ada)
        self.assertEqual(comment.trip(), self.trip)

    def test_a_user_with_no_grant_gets_a_404_not_a_403(self):
        self.login(self.cara)
        response = self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "I should not be able to do this"},
        )
        # 404, not 403: a 403 would confirm the trip exists.
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.exists())

    def test_an_unreadable_trip_404s_on_the_comment_page_too(self):
        self.login(self.cara)
        response = self.client.get(
            reverse("trips:comment_create", args=["trip", self.trip.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_a_logged_out_user_is_redirected(self):
        response = self.client.get(
            reverse("trips:comment_create", args=["trip", self.trip.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_a_user_without_a_grant_gets_a_404(self):
        # No grant means not readable, so the trip is invisible — and the
        # invisible trip is a 404, not a 403 that would confirm it exists.
        TripGrant.objects.filter(trip=self.trip, user=self.bob).delete()
        self.login(self.bob)
        response = self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "I can read but not comment"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.exists())

    def test_a_viewer_with_a_grant_gets_403_not_404(self):
        # Readable but not allowed to comment: the one case that is a 403.
        TripGrant.objects.filter(trip=self.trip, user=self.bob).update(role=TripRole.VIEWER)
        self.login(self.bob)
        response = self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "I can read but not comment"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Comment.objects.exists())

    def test_staff_can_post_without_a_grant(self):
        self.login(self.staff)
        response = self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "From the admin"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Comment.objects.get().author, self.staff)


class CommentTargetTests(CommentFixture):
    """The target is the thing commented on, and it comes from the URL."""

    def test_comments_attach_to_a_day_a_section_and_a_task(self):
        from apps.trips.models import BookingTask

        task = BookingTask.objects.create(trip=self.trip, title="Book the hotel")
        self.login(self.ada)

        for kind, pk in [
            ("day", self.day.pk),
            ("section", self.section.pk),
            ("task", task.pk),
        ]:
            with self.subTest(kind=kind):
                self.client.post(
                    reverse("trips:comment_create", args=[kind, pk]),
                    {"body": f"about the {kind}"},
                )

        self.assertEqual(Comment.objects.count(), 3)
        # All three resolve to the same trip, which is what makes access derived.
        for comment in Comment.objects.all():
            self.assertEqual(comment.trip(), self.trip)

    def test_a_day_id_from_another_trip_is_a_404(self):
        other = Trip.objects.create(
            name="Taos",
            start_date=date(2027, 3, 1),
            end_date=date(2027, 3, 8),
        )
        other_day = Day.objects.create(
            trip=other, day_number=1, date=date(2027, 3, 1)
        )
        self.login(self.ada)
        response = self.client.post(
            reverse("trips:comment_create", args=["day", other_day.pk]),
            {"body": "not my trip"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.exists())

    def test_an_unknown_target_kind_is_a_404(self):
        self.login(self.ada)
        response = self.client.post(
            reverse("trips:comment_create", args=["banana", self.trip.pk]),
            {"body": "nope"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.exists())

    def test_the_form_cannot_choose_its_own_target(self):
        # A hand-written post naming another trip's day must not attach there.
        # The form has no target field at all, so the URL is the only source.
        other = Trip.objects.create(
            name="Taos",
            start_date=date(2027, 3, 1),
            end_date=date(2027, 3, 8),
        )
        other_day = Day.objects.create(trip=other, day_number=1, date=date(2027, 3, 1))
        self.login(self.ada)

        self.client.post(
            reverse("trips:comment_create", args=["day", self.day.pk]),
            {
                "body": "trying to point this elsewhere",
                "content_type": "day",
                "object_id": other_day.pk,
            },
        )
        comment = Comment.objects.get()
        self.assertEqual(comment.content_object, self.day)

    def test_an_empty_comment_is_rejected(self):
        self.login(self.ada)
        response = self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "   "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Comment.objects.exists())
        self.assertContains(response, "Write something first.")

    def test_surrounding_whitespace_is_stripped(self):
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "  padded  "},
        )
        self.assertEqual(Comment.objects.get().body, "padded")


class CommentEditTests(CommentFixture):
    """Own comment or staff; not "anyone who can edit the trip"."""

    def setUp(self):
        super().setUp()
        self.comment = Comment.objects.create(
            author=self.ada, content_object=self.trip, body="Original"
        )

    def test_the_author_can_edit_their_own(self):
        self.login(self.ada)
        response = self.client.post(
            reverse("trips:comment_edit", args=[self.comment.pk]),
            {"body": "Revised"},
        )
        self.assertEqual(response.status_code, 302)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, "Revised")
        self.assertIsNotNone(self.comment.edited_at)

    def test_the_edit_page_itself_renders(self):
        # A working POST does not prove the page renders — the lesson from the
        # auth pages, where every URL was mounted and only `login.html` existed.
        self.login(self.ada)
        response = self.client.get(
            reverse("trips:comment_edit", args=[self.comment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Original")

    def test_someone_else_with_edit_access_cannot_rewrite_it(self):
        TripGrant.objects.filter(trip=self.trip, user=self.bob).update(role=TripRole.EDITOR)
        self.login(self.bob)
        response = self.client.post(
            reverse("trips:comment_edit", args=[self.comment.pk]),
            {"body": "Actually it said something else"},
        )
        # Bob may edit the trip. He may not edit Ada's remark about it.
        self.assertEqual(response.status_code, 403)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, "Original")

    def test_staff_can_edit_anyones(self):
        self.login(self.staff)
        response = self.client.post(
            reverse("trips:comment_edit", args=[self.comment.pk]),
            {"body": "Moderated"},
        )
        self.assertEqual(response.status_code, 302)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, "Moderated")

    def test_deleting_removes_it(self):
        self.login(self.ada)
        response = self.client.post(
            reverse("trips:comment_edit", args=[self.comment.pk]),
            {"action": "delete"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Comment.objects.filter(pk=self.comment.pk).exists())

    def test_a_user_who_cannot_see_the_trip_cannot_edit_a_comment_by_id(self):
        # Cara has a role but no grant. Guessing the comment id must not help:
        # the trip is resolved from the comment, then checked.
        self.login(self.cara)
        response = self.client.get(
            reverse("trips:comment_edit", args=[self.comment.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_an_untouched_edit_does_not_stamp_edited_at(self):
        fresh = Comment.objects.create(
            author=self.ada, content_object=self.trip, body="Same"
        )
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_edit", args=[fresh.pk]), {"body": "Same"}
        )
        fresh.refresh_from_db()
        self.assertIsNone(fresh.edited_at)


class OrphanCommentTests(CommentFixture):
    """A comment whose target is gone is a row nobody can reach."""

    def test_deleting_the_target_orphans_the_comment(self):
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["day", self.day.pk]),
            {"body": "about this day"},
        )
        self.assertEqual(Comment.objects.count(), 1)

        # A GenericForeignKey does not cascade, so the row survives.
        self.day.delete()
        orphan = Comment.objects.get()
        self.assertIsNone(orphan.content_object)
        self.assertIsNone(orphan.trip())

    def test_an_orphan_comment_is_a_404_for_everyone_including_staff(self):
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["day", self.day.pk]),
            {"body": "about this day"},
        )
        self.day.delete()
        orphan = Comment.objects.get()

        for user in (self.ada, self.staff):
            with self.subTest(user=user.username):
                self.login(user)
                response = self.client.get(
                    reverse("trips:comment_edit", args=[orphan.pk])
                )
                self.assertEqual(response.status_code, 404)


class CommentRenderingTests(CommentFixture):
    """Comments appear on the page their target is rendered on.

    That page is the *detail* page, not the editing page, and the distinction
    matters: the day and section edit pages require `edit`, so a commentor who is
    not an editor would have nowhere to read back what they wrote.
    """

    def test_the_detail_page_shows_the_trips_comments(self):
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "Someone read this"},
        )
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(response, "Someone read this")

    def test_a_day_comment_shows_on_the_detail_page(self):
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["day", self.day.pk]),
            {"body": "This day is too full"},
        )
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(response, "This day is too full")

    def test_a_commentor_who_is_not_an_editor_can_still_read_their_comment(self):
        # The regression this placement exists for: ada can comment but not edit,
        # so the day edit page 403s for her.
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["day", self.day.pk]),
            {"body": "posted by a non-editor"},
        )
        forbidden = self.client.get(
            reverse("trips:day_edit", args=[self.trip.pk, self.day.pk])
        )
        self.assertEqual(forbidden.status_code, 403)
        readable = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(readable, "posted by a non-editor")

    def test_posting_redirects_a_commentor_to_a_page_they_can_read(self):
        # Following the redirect is the whole point. Returning `day_edit` — the
        # page the target belongs to — would have passed the test above and still
        # left ada staring at a 403 after submitting the form.
        self.login(self.ada)
        response = self.client.post(
            reverse("trips:comment_create", args=["day", self.day.pk]),
            {"body": "where does this land?"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse("trips:trip_detail", args=[self.trip.pk]), response["Location"]
        )
        self.assertIn("#comments-day-%s" % self.day.pk, response["Location"])
        landed = self.client.get(response["Location"])
        self.assertEqual(landed.status_code, 200)
        self.assertContains(landed, "where does this land?")

    def test_every_target_kind_redirects_to_the_detail_page(self):
        # One rule for all four kinds, including the ones whose editing pages
        # live at different depths.
        from apps.trips.models import BookingTask

        task = BookingTask.objects.create(trip=self.trip, title="Book the hotel")
        self.login(self.ada)
        for kind, pk in [
            ("trip", self.trip.pk),
            ("day", self.day.pk),
            ("section", self.section.pk),
            ("task", task.pk),
        ]:
            with self.subTest(kind=kind):
                response = self.client.post(
                    reverse("trips:comment_create", args=[kind, pk]),
                    {"body": "anchor check for %s" % kind},
                )
                self.assertEqual(
                    response["Location"].split("#")[0],
                    reverse("trips:trip_detail", args=[self.trip.pk]),
                )
                self.assertIn("#comments-%s-%s" % (kind, pk), response["Location"])

    def test_a_section_comment_shows_on_the_detail_page(self):
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["section", self.section.pk]),
            {"body": "this warning is out of date"},
        )
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(response, "this warning is out of date")

    def test_a_task_comment_shows_on_the_detail_page(self):
        from apps.trips.models import BookingTask

        task = BookingTask.objects.create(trip=self.trip, title="Book the hotel")
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["task", task.pk]),
            {"body": "still looking at the spa place"},
        )
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(response, "still looking at the spa place")

    def test_a_comment_on_another_day_does_not_leak_into_this_one(self):
        other_day = Day.objects.create(
            trip=self.trip, day_number=2, date=date(2027, 9, 26), theme="Day two"
        )
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["day", other_day.pk]),
            {"body": "belongs to day two"},
        )
        response = self.client.get(
            reverse("trips:day_edit", args=[self.trip.pk, other_day.pk])
        )
        # other_day is rendered by the detail page, so compare against day one,
        # which is a different object with the same shape.
        detail = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(detail, "belongs to day two")
        # And the day-one thread block is absent entirely rather than empty.
        self.assertNotContains(
            detail, 'id="comments-day-%s"' % self.day.pk
        )

    def test_a_trip_with_no_comments_still_offers_the_add_link(self):
        # A commentor has to be able to *start* a thread, so an empty trip
        # renders the link rather than hiding itself.
        self.login(self.ada)
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(
            response, reverse("trips:comment_create", args=["trip", self.trip.pk])
        )

    def test_a_reader_who_cannot_comment_sees_no_thread_at_all(self):
        # Not "an empty heading and an empty list" — the block should not render,
        # because a viewer with nothing to say has nothing to look at.
        TripGrant.objects.filter(trip=self.trip, user=self.ada).update(role=TripRole.VIEWER)
        self.login(self.ada)
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertNotContains(response, "Nothing here yet.")
        self.assertNotContains(response, 'id="comments-trip-%s"' % self.trip.pk)

    def test_the_comment_thread_is_not_printed(self):
        # The detail page is the PDF artifact. A working conversation should not
        # end up in the printed copy.
        self.login(self.ada)
        self.client.post(
            reverse("trips:comment_create", args=["trip", self.trip.pk]),
            {"body": "internal chatter"},
        )
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(response, "internal chatter")
        # Every thread block carries no-print, which the stylesheet hides in
        # @media print.
        self.assertContains(response, 'class="no-print"')

    def test_a_viewer_without_the_comment_capability_sees_no_add_link(self):
        TripGrant.objects.filter(trip=self.trip, user=self.ada).update(role=TripRole.VIEWER)
        self.login(self.ada)
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertNotContains(
            response, reverse("trips:comment_create", args=["trip", self.trip.pk])
        )


class AnnotatedEditableTests(CommentFixture):
    """``annotate_editable`` must agree with ``Comment.can_edit``."""

    def test_the_annotation_matches_the_model_rule_for_every_user(self):
        ada_comment = Comment.objects.create(
            author=self.ada, content_object=self.trip, body="ada's"
        )
        bob_comment = Comment.objects.create(
            author=self.bob, content_object=self.trip, body="bob's"
        )

        for user in (self.ada, self.bob, self.staff):
            with self.subTest(user=user.username):
                for comment in (ada_comment, bob_comment):
                    annotated = (
                        Comment.objects.filter(pk=comment.pk)
                        .annotate_editable(user)
                        .get()
                        .can_edit
                    )
                    self.assertEqual(
                        annotated,
                        comment.can_edit(user),
                        f"{user.username} / {comment.author}",
                    )

    def test_an_inactive_account_is_told_it_can_edit_nothing(self):
        comment = Comment.objects.create(
            author=self.ada, content_object=self.trip, body="ada's"
        )
        self.ada.is_active = False
        self.ada.save()
        annotated = Comment.objects.filter(pk=comment.pk).annotate_editable(self.ada).get()
        self.assertFalse(annotated.can_edit)
