// The parts the firmware draws itself on top of the frame (§2).
#pragma once
#include "canvas.h"
#include "state.h"

void drawClockZone(Canvas &c);   // time, date, semester week
void drawStatusZone(Canvas &c);  // Wi-Fi, service, HA icons, or the offline bar

// The diagnostics screen (§5), drawn a line at a time: title, then one row per value.
constexpr int DIAG_LINES = 12;
constexpr int DIAG_LINE_MAX_H = 40;  // the title line; the rest are 24
Rect diagLine(int i);                 // where line i goes on the screen
void drawDiagLine(Canvas &c, int i);  // c is the size of diagLine(i)

// A notice the firmware shows by itself: a firmware update, its failure. The title and
// two rows, in the diagnostics' places.
constexpr int NOTICE_LINES = 3;
void drawNoticeLine(Canvas &c, int i, const char *text);
