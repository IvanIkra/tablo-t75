// The parts the firmware draws itself on top of the frame (§2).
#pragma once
#include "canvas.h"

void drawClockZone(Canvas &c);   // time, date, semester week
void drawStatusZone(Canvas &c);  // Wi-Fi, service, HA icons, or the offline bar
