from django.test import SimpleTestCase

from accounts.forms import AccountSettingsForm


class AccountSettingsFormCurrencyTests(SimpleTestCase):
    def test_currency_choices_are_iso_4217_codes(self):
        choices = dict(AccountSettingsForm().fields["preferred_currency"].choices)
        self.assertIn("USD", choices)
        self.assertIn("EUR", choices)
        self.assertTrue(all(len(code) == 3 and code.isupper() for code in choices))
