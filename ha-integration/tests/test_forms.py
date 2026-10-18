import pytest

from custom_components.tablo import forms


def test_wifi_round_trip_and_defaults():
    text = "Home | secret\nGuest\nLab | x | wep | hidden"
    got = forms.wifi_from_text(text)
    assert got == [
        {"ssid": "Home", "password": "secret", "security": "WPA", "hidden": False},
        {"ssid": "Guest", "password": "", "security": "nopass", "hidden": False},
        {"ssid": "Lab", "password": "x", "security": "WEP", "hidden": True},
    ]
    assert forms.wifi_from_text(forms.wifi_to_text(got)) == got


@pytest.mark.parametrize("text", ["Home | x | WPA2", "Home | x | WPA | yes", "A\nA"])
def test_wifi_errors(text):
    with pytest.raises(forms.FormError):
        forms.wifi_from_text(text)


def test_channels():
    got = forms.channels_from_text("@example_se study\nhttps://t.me/example_news3\n# comment\n\nexample_news2")
    assert got == [{"name": "example_se", "study": True}, {"name": "example_news3", "study": False},
                   {"name": "example_news2", "study": False}]
    assert forms.channels_from_text(forms.channels_to_text(got)) == got
    assert forms.channels_to_text(["plain"]) == "@plain"
    with pytest.raises(forms.FormError):
        forms.channels_from_text("@a weekly")
    with pytest.raises(forms.FormError):
        forms.channels_from_text("@a\n@A")


def test_sheets_and_subjects():
    sheets = forms.sheets_from_text("https://docs.google.com/x | Calc\nhttps://docs.google.com/y")
    assert sheets == [{"url": "https://docs.google.com/x", "label": "Calc"}, {"url": "https://docs.google.com/y"}]
    assert forms.sheets_from_text(forms.sheets_to_text(sheets)) == sheets
    with pytest.raises(forms.FormError):
        forms.sheets_from_text("Calc | https://docs.google.com/x")
    subjects = forms.subjects_from_text("Дискретная математика | Discrete Math | DM")
    assert subjects == [{"name": "Дискретная математика", "title": "Discrete Math", "abbr": "DM"}]
    assert forms.subjects_from_text(forms.subjects_to_text(subjects)) == subjects
    with pytest.raises(forms.FormError):
        forms.subjects_from_text("Матан | Calculus")


def test_home_rows_round_trip():
    text = "| {{ states('sensor.t') | round(1) }}°\nlights | {{ ['light.a'] | select('is_state', 'on') | list | count }} of 1"
    rows = forms.home_rows_from_text(text)
    assert rows == [{"label": "", "template": "{{ states('sensor.t') | round(1) }}°"},
                    {"label": "lights", "template": "{{ ['light.a'] | select('is_state', 'on') | list | count }} of 1"}]
    assert forms.home_rows_from_text(forms.home_rows_to_text(rows)) == rows
    # no "|" before the first brace: the whole line is the template
    assert forms.home_rows_from_text("{{ x | int }}") == [{"label": "", "template": "{{ x | int }}"}]


@pytest.mark.parametrize("text", ["door |", "\n".join(["{{ 1 }}"] * 6)])
def test_home_rows_errors(text):
    with pytest.raises(forms.FormError):
        forms.home_rows_from_text(text)
