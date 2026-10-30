// The parts the firmware draws itself on top of the frame (§2).
#pragma once
#include "canvas.h"
#include "state.h"

void drawClockZone(Canvas &c);   // time, date, semester week
void drawStatusZone(Canvas &c);  // Wi-Fi, service, HA icons, or the offline bar

// The diagnostics screen (§5), drawn a line at a time: title, then one row per value.
constexpr int DIAG_LINES = 12;
Rect diagLine(int i);                 // where line i goes on the screen
void drawDiagLine(Canvas &c, int i);  // c is the size of diagLine(i)
