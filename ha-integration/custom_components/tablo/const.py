"""Constants of the Tablo integration (§8)."""

DOMAIN = "tablo"

CONF_URL = "url"
CONF_API_TOKEN = "api_token"
OPT_CONFIG = "config"  # the service config, same shape as service/config.yaml (§6.5)
OPT_BOT = "bot"  # username of the infomaster bot, for the HSE login link; never sent to the service

DEFAULT_URL = "http://<host-ip>:8765"

BUTTON_EVENT = "tablo_button"  # fired by the service: {button, press}
CHANGED_EVENT = "tablo_changed"  # fired by the service: {kind: "status" / "messages"}
DISMISSED_EVENT = "tablo_message_dismissed"  # fired by the service: {title, text, sent_at, waiting}

POLL_SECONDS = 60  # events bring changes at once; the poll catches missed ones and the Wi-Fi level

BUTTONS = range(1, 9)  # 8 is fixed in firmware, but its presses still reach automations
CONFIGURABLE_BUTTONS = range(1, 8)
PRESSES = ("short", "long")

ACTIONS = ("toggle", "script", "qr", "message", "event", "none")
RUN_DOMAINS = ("script", "scene", "automation", "button", "input_button")
SOURCES = ("infomaster", "ical", "weather")
THEMES = ("dark", "light")  # dark: the panel shows everything white on black
DEFAULT_THEME = "dark"  # the service's default when the config has none
# Source settings that moved to infomaster's Mini App: an entry saved before still has them, the service refuses them.
OLD_CONFIG_KEYS = ("grades", "hseapp", "news", "mail", "subjects")

LOGIN_NOTIFICATION = "tablo_hseapp_login"
