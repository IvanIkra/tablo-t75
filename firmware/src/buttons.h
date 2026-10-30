// The 8 buttons under the screen: presses, instant tile marks, button 8 (§4, §5).
#pragma once
#include <stdint.h>

namespace buttons {

void begin();
void loop();  // handles presses read by the polling task, tile timeouts

void result(uint32_t seq);        // button_result: the tile shows its real state again
void settled(uint8_t tileMask);   // a new base frame changed these tiles: same as a result

enum Mark : uint8_t { NONE, INVERTED, FRAMED };
Mark mark(int tile);  // how the tile is drawn over the base frame now

}  // namespace buttons
