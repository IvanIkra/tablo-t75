#include "zones.h"

#include <Arduino.h>
#include <stdio.h>

#include "assets.h"
#include "state.h"

static const char *WEEKDAYS[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
static const char *MONTHS[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};

// Days since 1970-01-01 (Howard Hinnant's days_from_civil).
static long daysFromCivil(int y, int m, int d) {
  y -= m <= 2;
  long era = (y >= 0 ? y : y - 399) / 400;
  long yoe = y - era * 400;
  long doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  long doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + doe - 719468;
}

// Week 1 is the week (from Monday) of semester_start, as the emulator counts.
static int semesterWeek(const struct tm &t) {
  long today = daysFromCivil(t.tm_year + 1900, t.tm_mon + 1, t.tm_mday);
  long start = daysFromCivil(cfg.semYear, cfg.semMonth, cfg.semDay);
  long weekday = ((start + 4) % 7 + 7) % 7;  // 0 = Sunday; 1970-01-01 was a Thursday
  long monday = start - (weekday + 6) % 7;
  long diff = today - monday;
  return (diff >= 0 ? diff / 7 : (diff - 6) / 7) + 1;
}

void drawClockZone(Canvas &c) {
  c.clear();
  struct tm t;
  if (!localTimeNow(t)) return;  // blank until NTP: no wrong time on the wall
  char hhmm[6];
  snprintf(hhmm, sizeof hhmm, "%02d:%02d", t.tm_hour, t.tm_min);
  // Digits of one width: "HH:MM" is always 174 px and fits the 184 px zone.
  c.text(FONT_CLOCK, 6, 66, hhmm);
  char date[40];
  snprintf(date, sizeof date, "%s, %s %d \xC2\xB7 wk %d", WEEKDAYS[t.tm_wday], MONTHS[t.tm_mon],
           t.tm_mday, semesterWeek(t));
  c.text(FONT_DATE, 8, 90, date);
}

void drawStatusZone(Canvas &c) {
  if (serviceOffline()) {
    c.clear(true);
    char text[32] = "offline";
    struct tm t;
    if (localTimeNow(t)) {
      time_t since = time(nullptr) - (millis() - st.offlineSinceMs) / 1000;
      localtime_r(&since, &t);
      snprintf(text, sizeof text, "offline since %02d:%02d", t.tm_hour, t.tm_min);
    }
    int w = Canvas::textWidth(FONT_SEMI16, text);
    c.text(FONT_SEMI16, c.width() - 8 - w, 17, text, false);
    return;
  }
  // Online: icons only, right to left. The infomaster icon only while its data is old (§3.3).
  c.clear();
  uint32_t icons[4];
  int n = 0;
  icons[n++] = st.connected && health.ha ? ICON_HOME : ICON_HOME_OFF;
  icons[n++] = st.connected ? ICON_CLOUD : ICON_CLOUD_OFF;
  icons[n++] = st.wifiUp ? ICON_WIFI : ICON_WIFI_OFF;
  if (st.connected && !health.data) icons[n++] = ICON_DATA_OFF;
  int x = c.width() - 4;
  for (int i = 0; i < n; i++) {
    const Glyph *g = findGlyph(ICONS, icons[i]);
    if (!g) continue;
    c.glyph(ICONS, x - g->advance, 19, icons[i]);
    x -= g->advance + 5;
  }
}
