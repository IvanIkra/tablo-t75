// Copy to secrets.h (not in git) and fill in.
#pragma once

#define WIFI_SSID "your-ssid"
#define WIFI_PASSWORD "your-password"

#define SERVICE_HOST "192.168.1.50"
#define SERVICE_PORT 8765

#define DEVICE_ID "tablo"
// Same as TABLO_DEVICE_TOKEN in the service's .env (§10)
#define DEVICE_TOKEN "dev-device-token"

// For updates over Wi-Fi: pio run -e ota -t upload (TABLO_OTA_PASSWORD in the shell)
#define OTA_PASSWORD "change-me"
