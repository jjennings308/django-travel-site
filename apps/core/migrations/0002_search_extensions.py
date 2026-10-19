"""Postgres extensions for catalogue search (site roadmap R20): pg_trgm (typo-tolerant name matching)
and unaccent (München = Munchen). Both are "trusted" on Postgres 13+, so the database owner can create
them without a superuser."""
from django.contrib.postgres.operations import TrigramExtension, UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        TrigramExtension(),
        UnaccentExtension(),
    ]
