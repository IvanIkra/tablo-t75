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
