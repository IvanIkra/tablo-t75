// Display bring-up for Tablo T75.
// 1. Full refresh: test pattern (edges, grid, fine lines, black and dithered blocks).
// 2. Partial refresh of a small window (counter), like the clock.
// 3. Partial refresh of the whole screen, like a new frame by diff.
// 4. Pause to look at ghosting, then full refresh with the measured times.
// Times go to Serial (115200). Press RESET to run again.

#include <Arduino.h>
#include <GxEPD2_BW.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/FreeSansBold18pt7b.h>
#include <Fonts/FreeSansBold24pt7b.h>

// ESP32-L(C02) + DESPI-C02 wiring (Good Display kit, same as GxEPD2 examples).
// SPI: SCK 18, MOSI 23.
constexpr int PIN_CS = 27;
constexpr int PIN_DC = 14;
constexpr int PIN_RST = 12;
constexpr int PIN_BUSY = 13;

GxEPD2_BW<GxEPD2_750_GDEY075T7, GxEPD2_750_GDEY075T7::HEIGHT> display(
    GxEPD2_750_GDEY075T7(PIN_CS, PIN_DC, PIN_RST, PIN_BUSY));

constexpr int W = 800;
constexpr int H = 480;

constexpr int SMALL_RUNS = 20;
constexpr int SCREEN_RUNS = 6;

static void printCentered(const char *text, int cx, int baseline) {
  int16_t x1, y1;
  uint16_t w, h;
  display.getTextBounds(text, 0, 0, &x1, &y1, &w, &h);
  display.setCursor(cx - w / 2 - x1, baseline);
  display.print(text);
}

static void drawPattern() {
  display.fillScreen(GxEPD_WHITE);
  display.setTextColor(GxEPD_BLACK);

  // Outer 1 px border and a second one 4 px in: both must be fully visible.
  display.drawRect(0, 0, W, H, GxEPD_BLACK);
  display.drawRect(4, 4, W - 8, H - 8, GxEPD_BLACK);

  // Dotted grid every 100 px.
  for (int x = 100; x < W; x += 100)
    for (int y = 8; y < H - 8; y += 4) display.drawPixel(x, y, GxEPD_BLACK);
  for (int y = 100; y < H; y += 100)
    for (int x = 8; x < W - 8; x += 4) display.drawPixel(x, y, GxEPD_BLACK);

  // Corner labels.
  display.setFont(&FreeSans12pt7b);
  display.setCursor(12, 30);
  display.print("0,0");
  display.setCursor(W - 100, H - 14);
  display.print("799,479");

  display.setFont(&FreeSansBold24pt7b);
  printCentered("TABLO T75", W / 2, 80);
  display.setFont(&FreeSans12pt7b);
  printCentered("Display test - GDEY075T7", W / 2, 115);

  // Fine lines: 1, 2, 3 px wide with equal gaps.
  for (int i = 0; i < 3; i++) {
    int step = (i + 1) * 2;
    int x0 = 40 + i * 120;
    for (int x = x0; x < x0 + 100; x += step)
      display.fillRect(x, 150, i + 1, 80, GxEPD_BLACK);
  }

  // Solid black and checkerboard (50% dither).
  display.fillRect(420, 150, 150, 80, GxEPD_BLACK);
  for (int y = 150; y < 230; y++)
    for (int x = 600; x < 760; x++)
      if ((x + y) & 1) display.drawPixel(x, y, GxEPD_BLACK);

  // Small text, the size the service uses for news lines.
  display.setFont(nullptr);
  display.setTextSize(1);
  display.setCursor(40, 260);
  display.print("Small 6x8 text: The quick brown fox jumps over the lazy dog 0123456789");
  display.setTextSize(2);
  display.setCursor(40, 280);
  display.print("Size 2: Deadlines  Grades  Classes  Weather");
}

static unsigned long timeFull() {
  unsigned long t = millis();
  display.display(false);
  return millis() - t;
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n\nTablo T75 display bring-up");

  // 2 ms reset pulse: needed for DESPI-C02 style reset circuits.
  display.init(115200, true, 2, false);
  display.setRotation(0);

  // 1. Full refresh.
  drawPattern();
  unsigned long fullMs = timeFull();
  Serial.printf("Full refresh: %lu ms\n", fullMs);
  delay(2000);

  // 2. Small partial window (counter where a clock would be).
  const int bx = 480, by = 320, bw = 240, bh = 120;  // x and width multiples of 8
  unsigned long smallSum = 0, smallMax = 0;
  display.setFont(&FreeSansBold24pt7b);
  for (int i = 1; i <= SMALL_RUNS; i++) {
    display.fillRect(bx, by, bw, bh, GxEPD_WHITE);
    display.drawRect(bx, by, bw, bh, GxEPD_BLACK);
    char buf[16];
    snprintf(buf, sizeof buf, "%02d:%02d", i, (i * 7) % 60);
    printCentered(buf, bx + bw / 2, by + 75);
    unsigned long t = millis();
    display.displayWindow(bx, by, bw, bh);
    unsigned long dt = millis() - t;
    smallSum += dt;
    if (dt > smallMax) smallMax = dt;
    Serial.printf("Partial %dx%d #%d: %lu ms\n", bw, bh, i, dt);
    delay(300);
  }

  // 3. Whole-screen partial: invert a large block back and forth.
  unsigned long screenSum = 0, screenMax = 0;
  for (int i = 1; i <= SCREEN_RUNS; i++) {
    drawPattern();
    if (i & 1) display.fillRect(40, 320, 400, 140, GxEPD_BLACK);
    display.setFont(&FreeSansBold18pt7b);
    display.setTextColor((i & 1) ? GxEPD_WHITE : GxEPD_BLACK);
    char buf[32];
    snprintf(buf, sizeof buf, "Frame %d", i);
    printCentered(buf, 240, 400);
    display.setTextColor(GxEPD_BLACK);
    unsigned long t = millis();
    display.display(true);
    unsigned long dt = millis() - t;
    screenSum += dt;
    if (dt > screenMax) screenMax = dt;
    Serial.printf("Partial full screen #%d: %lu ms\n", i, dt);
    delay(500);
  }

  Serial.println("Look at the screen now for ghosting. Full refresh in 10 s.");
  delay(10000);

  // 4. Results, full refresh.
  display.fillScreen(GxEPD_WHITE);
  display.drawRect(0, 0, W, H, GxEPD_BLACK);
  display.setTextColor(GxEPD_BLACK);
  display.setFont(&FreeSansBold24pt7b);
  printCentered("Display OK", W / 2, 110);
  display.setFont(&FreeSans12pt7b);
  char line[64];
  snprintf(line, sizeof line, "Full refresh: %lu ms", fullMs);
  printCentered(line, W / 2, 190);
  snprintf(line, sizeof line, "Partial %dx%d: avg %lu ms, max %lu ms", bw, bh,
           smallSum / SMALL_RUNS, smallMax);
  printCentered(line, W / 2, 230);
  snprintf(line, sizeof line, "Partial full screen: avg %lu ms, max %lu ms",
           screenSum / SCREEN_RUNS, screenMax);
  printCentered(line, W / 2, 270);
  printCentered("Press RESET to run again", W / 2, 400);
  display.display(false);
  display.hibernate();

  Serial.printf("Summary: full %lu ms, small partial avg %lu / max %lu ms, "
                "screen partial avg %lu / max %lu ms\n",
                fullMs, smallSum / SMALL_RUNS, smallMax, screenSum / SCREEN_RUNS,
                screenMax);
}

void loop() {}
