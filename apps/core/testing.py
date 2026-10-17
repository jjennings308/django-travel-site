"""Test helpers shared by every app (core is layer 0, so any app's tests may import this)."""
from django.db import connections
from django.test import TransactionTestCase


class RestoringTransactionTestCase(TransactionTestCase):
    """A TransactionTestCase that leaves the database as it found it.

    A TransactionTestCase empties every table when it ends, including the rows data migrations
    seeded (locations 0012's place types, notification kinds, approval queues). Django's
    ``serialized_rollback`` reloads them only at the *start* of the next such test, so the last one
    still leaves its database empty — and with ``--keepdb`` the emptied parallel test copies
    (``test_<db>_1`` …) survive into the next run, where every test that needs those rows fails.
    This class also reloads the starting contents *after* emptying. Use it for any test that needs
    real transactions (e.g. stepping migrations back and forth).
    """

    serialized_rollback = True

    def _fixture_teardown(self):
        super()._fixture_teardown()
        for alias in self._databases_names(include_mirrors=False):
            contents = getattr(connections[alias], "_test_serialized_contents", None)
            if contents:
                connections[alias].creation.deserialize_db_from_string(contents)
