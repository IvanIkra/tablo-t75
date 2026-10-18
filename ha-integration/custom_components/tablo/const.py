"""Constants of the Tablo integration (§8)."""

DOMAIN = "tablo"

CONF_URL = "url"
CONF_API_TOKEN = "api_token"
OPT_CONFIG = "config"  # the service config, same shape as service/config.yaml (§6.5)

DEFAULT_URL = "http://192.168.1.50:8765"

BUTTON_EVENT = "tablo_button"  # fired by the service: {button, press}
CHANGED_EVENT = "tablo_changed"  # fired by the service: {kind: "status" | "deadlines"}

POLL_SECONDS = 60  # events bring changes at once; the poll catches missed ones and the Wi-Fi level

BUTTONS = range(1, 9)  # 8 is fixed in firmware, but its presses still reach automations
CONFIGURABLE_BUTTONS = range(1, 8)
PRESSES = ("short", "long")

ACTIONS = ("toggle", "script", "qr", "message", "event", "none")
RUN_DOMAINS = ("script", "scene", "automation", "button", "input_button")
SOURCES = ("grades", "hseapp", "ical", "news", "weather")
LLM_TASKS = ("news", "grades", "deadlines", "subjects")  # what the service calls Haiku for (§6.6)

LOGIN_NOTIFICATION = "tablo_hseapp_login"
