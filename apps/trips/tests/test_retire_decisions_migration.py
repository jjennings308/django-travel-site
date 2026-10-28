"""trips 0054–0055 (docs/plans/retire-decision-todos.md, D2): a to-do's options go into its notes before
``TaskOption`` and ``BookingTask.kind`` are dropped; an open to-do that still has options stops it."""
from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.core.testing import RestoringTransactionTestCase


class RetireDecisionsMigrationTests(RestoringTransactionTestCase):
    BEFORE = [("trips", "0053_cover_photo")]
    AFTER = [("trips", "0055_remove_decision_todos")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def task(self, apps, **fields):
        Trip = apps.get_model("trips", "Trip")
        trip = Trip.objects.create(name="Old trip", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        return apps.get_model("trips", "BookingTask").objects.create(trip=trip, kind="decide", **fields)

    def test_closed_todos_keep_their_options_in_their_notes(self):
        apps = self.migrate(self.BEFORE)
        TaskOption = apps.get_model("trips", "TaskOption")
        task = self.task(apps, title="Which hotel", done=True, notes="Booked in May")
        TaskOption.objects.create(task=task, title="Drei Mohren", order=2)
        TaskOption.objects.create(task=task, title="Augusta", order=1, chosen=True)
        plain = self.task(apps, title="Seats", notes="Window")
        apps = self.migrate(self.AFTER)
        BookingTask = apps.get_model("trips", "BookingTask")
        self.assertEqual(BookingTask.objects.get(pk=task.pk).notes,
                         "Booked in May\nOptions considered: Augusta (chosen); Drei Mohren")
        self.assertEqual(BookingTask.objects.get(pk=plain.pk).notes, "Window")
        self.assertNotIn("kind", [f.name for f in BookingTask._meta.get_fields()])
        with connection.cursor() as cursor:
            self.assertNotIn("trips_taskoption", connection.introspection.table_names(cursor))

    def test_an_open_todo_with_options_stops_it(self):
        apps = self.migrate(self.BEFORE)
        TaskOption = apps.get_model("trips", "TaskOption")
        task = self.task(apps, title="Which hotel")
        TaskOption.objects.create(task=task, title="Augusta")
        with self.assertRaisesMessage(RuntimeError, f"Open to-dos still have options: run `manage.py "
                                                    f"convert_day_first --all --apply` (on the D1 code) first. "
                                                    f"Trips: {task.trip_id}"):
            self.migrate(self.AFTER)
        TaskOption.objects.all().delete()
