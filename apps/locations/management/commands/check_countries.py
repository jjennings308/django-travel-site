"""Compare our countries with REST Countries and print where they differ (country-flags plan C2).

    .venv/bin/python manage.py check_countries                # every country (three API requests)
    .venv/bin/python manage.py check_countries --country ZW   # one (one request)

Monthly on production with ``--email`` (``scripts/README.md``). For each of our countries with an
``iso_code`` it compares ``name`` (their common, official or alternate name), ``iso3_code``, ``currency_code`` (ours
one of theirs; the others are noted), ``currency_name`` (that currency's name), ``phone_code`` (one of their calling
codes, ignoring "+", spaces and dashes) and ``continent`` (one of theirs), all ignoring case and extra spaces, and
prints one line per difference ("ZW currency_code: ours ZWL, theirs ZWG"). Then our countries they don't know, and
— one line, as information — the codes they have that we don't (territories mostly).

Exit 0 when nothing differs, 1 when something does (a difference, or one of ours they don't know), 2 when the API
couldn't be read or the key is missing. ``--email`` (the monthly cron, through ``scripts/run_job.sh``) also emails the
differences to ``DJANGO_ADMINS`` (``core.job_mail``; script-emails plan M1) and then exits 0, so the wrapper doesn't
mail them a second time; an API error still exits 2, which the wrapper reports. Stores nothing: their terms allow keeping their data for at most three
days, so it stays in memory for the run; James edits a country by hand (or by CSV import) if he agrees.
"""
import sys

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.locations import restcountries
from apps.locations.models import Country


def _norm(value):
    return " ".join(str(value or "").split()).casefold()


def _digits(code):
    return "".join(c for c in str(code or "") if c.isdigit())


class Command(BaseCommand):
    help = "Print where our countries differ from REST Countries (stores nothing; exit 1 when something differs)."

    def add_arguments(self, parser):
        parser.add_argument("--country", help="One country's two-letter code.")
        parser.add_argument("--email", action="store_true",
                            help="Also email the differences to DJANGO_ADMINS (then exit 0).")

    def handle(self, *args, country=None, email=False, **options):
        try:
            theirs = restcountries.fetch(getattr(settings, "RESTCOUNTRIES_API_KEY", ""), alpha_2=country)
        except restcountries.ApiError as error:
            self.stderr.write(str(error))
            sys.exit(2)
        by_code = {c["alpha_2"]: c for c in theirs if c["alpha_2"]}
        ours = Country.objects.exclude(iso_code="").order_by("iso_code")
        if country:
            ours = ours.filter(iso_code__iexact=country.strip())
        lines, notes, unknown = [], [], []
        for row in ours:
            code = row.iso_code.upper()
            other = by_code.pop(code, None)
            if other is None:
                unknown.append(f"{code} {row.name}")
                continue
            lines += [f"{code} {line}" for line in self._differences(row, other, notes)]
        report = [f"Compared {ours.count()} of our countries with REST Countries.", *lines]
        if unknown:
            report.append(f"Ours they don't know ({len(unknown)}): {', '.join(unknown)}")
        if notes:
            report += ["Notes:", *(f"  {note}" for note in notes)]
        if by_code and not country:
            report.append(f"Theirs we don't have ({len(by_code)}): {', '.join(sorted(by_code))}")
        for line in report:
            self.stdout.write(line)
        if not lines and not unknown:
            self.stdout.write(self.style.SUCCESS("No differences."))
            return
        count = len(lines) + len(unknown)
        self.stdout.write(self.style.WARNING(f"{count} to look at."))
        if email:
            from apps.core import job_mail
            sent = job_mail.report(f"check_countries: {count} to look at", "\n".join(
                report + ["", "Edit a country by hand (or by CSV import) where you agree. Nothing was changed."]))
            self.stdout.write("Emailed to DJANGO_ADMINS." if sent else "Not emailed (DJANGO_ADMINS empty or mail failed).")
            if sent:
                return
        sys.exit(1)

    @staticmethod
    def _differences(row, other, notes):
        code = row.iso_code.upper()
        names = [other["common"], other["official"], *other["alternates"]]
        if _norm(row.name) not in {_norm(n) for n in names if n}:
            yield f"name: ours {row.name}, theirs {other['common'] or other['official']}"
        if other["alpha_3"] and _norm(row.iso3_code) != _norm(other["alpha_3"]):
            yield f"iso3_code: ours {row.iso3_code or '—'}, theirs {other['alpha_3']}"
        money = dict(other["currencies"])
        if money:
            mine = (row.currency_code or "").upper()
            if mine not in money:
                yield f"currency_code: ours {mine or '—'}, theirs {', '.join(money)}"
            else:
                if len(money) > 1:
                    notes.append(f"{code} also uses {', '.join(c for c in money if c != mine)} (ours: {mine})")
                if money[mine] and row.currency_name and _norm(row.currency_name) != _norm(money[mine]):
                    yield f"currency_name: ours {row.currency_name}, theirs {money[mine]}"
        calling = {_digits(c) for c in other["calling_codes"] if _digits(c)}
        if calling and _digits(row.phone_code) not in calling:
            yield f"phone_code: ours {row.phone_code or '—'}, theirs {', '.join('+' + c for c in sorted(calling))}"
        continents = {_norm(c) for c in other["continents"]}
        if continents and _norm(row.continent) not in continents:
            yield f"continent: ours {row.continent or '—'}, theirs {', '.join(other['continents'])}"
