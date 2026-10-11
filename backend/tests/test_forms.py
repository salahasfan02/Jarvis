"""The user's details and which form fields they go in."""
from app.memory import profile
from app.tools.builtin import forms


def test_form_labels_map_to_details():
    cases = {"Full name": "full_name", "First name": "first_name", "Surname": "last_name",
             "Email address": "email", "Mobile phone": "phone", "Address line 1": "address_line1",
             "Address line 2": "address_line2", "Town/City": "city", "Postcode": "postcode",
             "ZIP code": "postcode", "Country": "country", "Company name": "company"}
    for label, key in cases.items():
        assert profile.key_for(label) == key, label


def test_sensitive_fields_are_never_filled():
    for label in ("Password", "Card number", "CVV", "Expiry date", "Sort code", "IBAN",
                  "National Insurance number", "Passport number", "One-time code"):
        assert profile.key_for(label) is None and profile.NEVER.search(label), label


def test_details_are_saved_and_split_into_first_and_last(monkeypatch):
    assert "Saved" in forms.update_my_details(full_name="Ada Lovelace", email="ada@example.com",
                                              password="nope")
    p = profile.get()
    assert p["first_name"] == "Ada" and p["last_name"] == "Lovelace" and "password" not in p
    assert "Email: ada@example.com" in forms.my_details()
