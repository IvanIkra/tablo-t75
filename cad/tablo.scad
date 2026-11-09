// Tablo T75 — printable enclosure for a 7.5" e-paper desk/wall display
//
// Parts (set `part`):
//   front         front shell: bezel, screen window, key plate, side ports   (print face down)
//   back          back cover: wall keyholes, board clips, adapter pad        (print outer face down)
//                 (with board = "custom": battery fence, board posts, pockets over the module and USB-C)
//   leg           rear desk leg, hooks into the wall keyholes, 15°            (print bar face down)
//   peg           mushroom peg ×2, glued into the leg bar instead of screws  (print cap down)
//   wall_mount    T plate taped to the wall, 2 glued pegs hold the body     (print wall face down)
//   keycap        pill keycap ×7, keycap_dimple ×1 ("all off")               (print top face down)
//   key_plate     separate 1.3 mm switch plate: clip the switches in, then screw it in from the back
//   key_test      2-key coupons of the front wall and the plate — PRINT THESE FIRST to tune the Choc fit
//   assembly_*    previews only
//
// Device coordinates: x across, y up (0 = bottom edge), z depth (0 = front face).
// Seen from the FRONT, +x runs to the viewer's LEFT; seen from the BACK, +x runs right.
//
// Sources: GDEY075T7 outline drawing (good-display.com/product/396.html);
// ESP32-L(C02) 70×54 mm, DESPI-C02 41×22 mm (buy-lcd.com product page).
// Values marked MEASURE are estimates — check them with calipers before printing.

// Which electronics the enclosure is for: the Good Display ESP32-L + DESPI-C02 kit,
// or Tablo's own board (pcb/, see docs/hardware.md "Custom board").
board = "esp32l"; // [esp32l, custom]

part = "assembly_desk"; // [assembly_desk, assembly_side, assembly_wall, assembly_back, assembly_open, exploded, front, back, leg, peg, wall_mount, key_plate, keycap, keycap_dimple, key_test]

/* [Body] */
W = 185;  H = 146;  T = 17;  R = 6;
wall = 2;  front_t = 2;  back_t = 2.5;
front_chamfer = 1.5;         // 45° chamfer around the front edge (prints fine face down)
back_chamfer = 1.0;          // 45° chamfer around the back cover edge
pill_chamfer = 0.5;          // small chamfer on the key openings

/* [Panel GDEY075T7 — from the datasheet drawing] */
pan_w = 170.2;  pan_h = 111.2;  pan_t = 1.25;
act_w = 163.2;  act_h = 97.92;
act_off_top = 3.49;          // active area top -> panel top edge
fpc_from_right = 79.9;       // FPC centre from the panel's right edge, seen from the front
fpc_w = 12.5;  fpc_len = 24;
tape_t = 0.5;                // double-sided tape between bezel and panel
top_bezel = 12;              // body top edge -> active area
win_clr = 0.4;               // window oversize per side
fpc_gap = 3;                 // room for the FPC bend under the panel

/* [Keys: Kailh Choc v1 — MEASURE / tune with key_test] */
n_keys = 8;
pill_w = 16.4;  pill_h = 12;  pill_clr = 0.4;
plate_t = 1.3;               // Choc clips need a 1.2–1.3 mm plate
choc_cut = 13.8;             // plate cut-out
choc_house = 15.4;           // pocket for the 15×15 top housing
skin = 4.0;                  // front skin above the housing pocket (housing top sits 0.8 mm deeper)
stem_top_rest = 4.6;         // stem top above plate at rest (MEASURE)
house_above_plate = 1.8;     // top housing height above plate (MEASURE)
below_plate = 2.2;           // bottom housing below the plate
cap_t = 3.0;  cap_recess = 1.0;  travel = 3.0;
cap_protrude = 0;            // cap top above the front face at rest: 0 = flush, the key sinks in when pressed

/* [Keycap legs, Choc v1 — MEASURE] */
stem_w = 1.15;  stem_l = 3.0;  stem_h = 3.0;  stem_dx = 5.7;

/* [Fasteners: M2.5 brass heat-set inserts M2.5×3×4 (L 3, OD 4)] */
insert_d = 3.6;  insert_l = 3.0;   // hole for the insert (OD 4 → 3.6 hole), insert length
screw_clear = 2.8;                 // M2.5 clearance
// back cover: 4 × M2.5×8 countersunk DIN 965 into inserts in the corner bosses
boss_d = 7;  clear_d = 2.8;  cover_screw_l = 8;
// switch plate: 3 × M2.5×6 cylinder head (Torx) into inserts in the key block
plate_screw_l = 6;  plate_boss_d = 6;

/* [Board ESP32-L(C02), 70×54, headers removed] */
board_w = 70;  board_h = 54;  pcb_t = 1.6;
board_x = 3.0;               // Type-C edge against the right side wall (seen from the front)
board_y = 60;
comp_h = 5.0;                // tallest part on the component side (reset button) — MEASURE
usbc_from_bottom = 32.5;     // Type-C centre from the board's bottom edge — MEASURE
switch_from_bottom = 13.8;   // power slide switch from the board's bottom edge — MEASURE
usbc_open = [12.5, 6.5];     // side opening, sized for the plug overmould
switch_open = [8, 4];

/* [Custom board (pcb/tablo.kicad_pcb), seen from the back: x as here, y up] */
pcb2 = [2.5, 8.7, 176, 50.3];          // x0, y0, x1, y1 of the board outline
pcb2_slot = [80.3, 23.5, 94.3, 25.5];// the screen FPC goes back through this slot
usb2_y = 36;  sw2_y = 19;            // USB-C and power switch centres on the left end
usb2_open = [12.5, 6.5];  sw2_open = [8, 3];
module2 = [107, 25.9, 18, 19.2];     // ESP32-S3-WROOM-1U: x, y, w, h (3.2 mm tall)
battery2 = [60, 52, 60.5, 40.5, 6];  // LiPo 604060 bay: x, y, w, h, thickness
pocket_d = 1.0;                      // pockets in the cover over the tall parts

/* [Adapter DESPI-C02, 41×22, on tape] */
adp_w = 41;  adp_h = 22;  adp_pad_h = 6;   // keeps the adapter where it was, within reach of the FPC

/* [Wall keyholes] */
kh_y = H - 20;  kh_dx = 52.5;  kh_d = 9;  kh_slot = 4.5;  kh_len = 8;

/* [Rear desk leg: hangs on the two wall screws, invisible from the front] */
tilt = 15;              // screen tilt on the desk
leg_bar = [124, 20, 6]; // cross bar on the back: width, height, thickness
leg_t = 6;              // fin thickness
leg_contact = [40, 138];// fin touches the back from this height to this height
leg_foot = [62, 86];    // fin foot, measured out from the back face (it lands on the desk line)
screw_pilot = 3.2;      // for the same M4 / Ø4 screws used on the wall
screw_gap = 2.8;        // leave the screw head this far from the bar (cover thickness + play)
// printed mushroom pegs instead of the screws: the stem is glued into the pilot hole,
// the neck rides in the 4.5 mm slot, the cap goes in through the 9 mm hole and sits in the 3 mm channel
peg_cap = [8, 2];       // cap diameter, thickness (like the screw head)
peg_neck = 4;           // neck diameter, its length is screw_gap: the shoulder stops on the bar
peg_stem = [2.9, 3.6];  // stem diameter (pilot hole 3.2 leaves room for glue), length (hole is 4 deep)

/* [Wall mount: T plate on double-sided tape with two pegs printed in one piece, hidden behind the body] */
mount_t = 5;            // plate thickness = gap between the back and the wall
mount_bar = [124, 20];  // cross bar through the two pegs: width, height
mount_stem = [32, 24];  // stem width, its bottom edge above the body's bottom; the back rests on it, so the body hangs parallel to the wall
mount_chamfer = 0.8;    // 45° on both faces (the bed side also hides elephant foot)

$fn = 48;
eps = 0.01;

// ---------- derived ----------
pitch = act_w / n_keys;
inner_back = T - back_t;
act_x0 = (W - act_w) / 2;
act_y1 = H - top_bezel;           act_y0 = act_y1 - act_h;
pan_x0 = (W - pan_w) / 2;         // panel right edge (seen from the front) is at small x
pan_y1 = act_y1 + act_off_top;    pan_y0 = pan_y1 - pan_h;
fpc_x = pan_x0 + fpc_from_right;
key_block_y1 = pan_y0 - fpc_gap;
key_cy = key_block_y1 - choc_house / 2 - 0.5;
plate_z0 = stem_top_rest + (cap_t - cap_recess) - cap_protrude;   // front face -> plate top
key_block_d = plate_z0;                              // the shell stops at the plate; the plate is a separate part
plate_screws = [0.5, 3.5, 6.5];                      // between keys 0|1, 3|4, 6|7
plate_screw_y = wall + 2.6;                          // below the key pockets, where the block is solid
plate_boss_h = max(0, plate_screw_l - plate_t - insert_l);   // raised pads so a 6 mm screw ends inside the insert
board_comp_z = inner_back - comp_h - 0.3;     // component face (faces the back cover)
board_sold_z = board_comp_z - pcb_t;          // solder face (faces the panel)
pcb2_z = plate_z0 + plate_t + below_plate;    // custom board: face towards the plate
pcb2_back = pcb2_z + pcb_t;                    // custom board: component face
custom = board == "custom";
usbc_y = custom ? usb2_y : board_y + usbc_from_bottom;
usbc_z = custom ? pcb2_back + 1.6 : board_comp_z + 1.6;
switch_y = custom ? sw2_y : board_y + switch_from_bottom;
switch_z = custom ? pcb2_back + 0.8 : usbc_z;
adp_x = fpc_x - adp_w / 2;  adp_y = pan_y0 + 9;
function kx(i) = W / 2 - (i - (n_keys - 1) / 2) * pitch;   // key 0 = leftmost seen from the front
boss_pts = [[5.5, 5], [W - 5.5, 5], [5.5, H - 5], [W - 5.5, H - 5]];

assert(key_cy - choc_house / 2 > wall + 0.5, "keys collide with the bottom wall");
assert(plate_z0 + plate_t + below_plate + 1.5 < inner_back, "too thin for the switches");
assert(custom || board_sold_z - (front_t + tape_t + pan_t) > 1.2, "board touches the panel");
assert(!custom || pcb2_back + 3.2 + 0.3 < inner_back + pocket_d, "custom board: no room for the module");
assert(!custom || pcb2[1] > boss_pts[0][1] + boss_d / 2, "custom board hits the corner bosses");

// ---------- helpers ----------
module rrect(w, h, r) { translate([r, r]) offset(r) square([w - 2 * r, h - 2 * r]); }
module stadium(w, h) { hull() for (s = [-1, 1]) translate([s * (w - h) / 2, 0]) circle(d = h); }
// rounded-rect slab from z0 to z1 with a 45° chamfer of size c on the z0 face
module chamfered_slab(z0, z1, c) {
  hull() {
    translate([0, 0, z0]) linear_extrude(eps) offset(-c) rrect(W, H, R);
    translate([0, 0, z0 + c]) linear_extrude(z1 - z0 - c) rrect(W, H, R);
  }
}
module side_hole(y, z, size) {   // through the right side wall (small x)
  translate([-1, y, z]) rotate([0, 90, 0]) rotate([0, 0, 90]) linear_extrude(wall + 4) stadium(size[0], size[1]);
}

// ---------- front shell ----------
module front_shell() {
  difference() {
    union() {
      difference() {
        chamfered_slab(0, inner_back, front_chamfer);
        translate([0, 0, front_t]) linear_extrude(T) offset(-wall) rrect(W, H, R);
      }
      translate([act_x0 - 1, wall - eps, 0]) cube([act_w + 2, key_block_y1 - wall, key_block_d]);   // key plate block
      panel_rails();
      for (p = boss_pts) translate([p[0], p[1], 0]) cylinder(d = boss_d, h = inner_back);
      if (!custom) {
        translate([wall - eps, usbc_y - 10, front_t]) cube([2, 20, inner_back - front_t]);             // thicker wall at the ports
        translate([wall - eps, switch_y - 7, front_t]) cube([2, 14, inner_back - front_t]);
      }
    }
    // window, chamfered outside
    translate([act_x0 + act_w / 2, act_y0 + act_h / 2, 0]) hull() {
      translate([0, 0, -eps]) linear_extrude(eps) square([act_w + 2 * win_clr + 2.4, act_h + 2 * win_clr + 2.4], center = true);
      translate([0, 0, 1.2]) linear_extrude(front_t) square([act_w + 2 * win_clr, act_h + 2 * win_clr], center = true);
    }
    // keys: pill opening through to the plate, square pocket for the housing, plate cut-out
    for (i = [0 : n_keys - 1]) translate([kx(i), key_cy, 0]) {
      translate([0, 0, -1]) linear_extrude(plate_z0 + 1) offset(pill_clr) stadium(pill_w, pill_h);
      hull() {
        translate([0, 0, -eps]) linear_extrude(eps) offset(pill_clr + pill_chamfer) stadium(pill_w, pill_h);
        translate([0, 0, pill_chamfer]) linear_extrude(eps) offset(pill_clr) stadium(pill_w, pill_h);
      }
      translate([-choc_house / 2, -choc_house / 2, skin]) cube([choc_house, choc_house, plate_z0 - skin + eps]);
    }
    for (g = plate_screws) translate([kx(g), plate_screw_y, plate_z0 - insert_l - 0.5]) cylinder(d = insert_d, h = insert_l + 1);   // inserts for the plate
    for (p = boss_pts) translate([p[0], p[1], 0]) {
      translate([0, 0, inner_back - insert_l - 0.5]) cylinder(d = insert_d, h = insert_l + 1);                 // insert
      translate([0, 0, inner_back - (cover_screw_l - back_t) - 1.5]) cylinder(d = screw_clear, h = cover_screw_l); // room for the screw tip
    }
    ports();
  }
}

module panel_rails() {
  c = 0.3; rw = 1.2; rh = tape_t + pan_t + 0.4;
  translate([0, 0, front_t - eps]) {
    translate([pan_x0 - c - rw, pan_y0 + 10, 0]) cube([rw, pan_h - 10, rh]);
    translate([pan_x0 + pan_w + c, pan_y0 + 10, 0]) cube([rw, pan_h - 10, rh]);
    translate([pan_x0 + 8, pan_y1 + c, 0]) cube([pan_w - 16, rw, rh]);
    // bottom stops, leaving the FPC free
    for (x = [pan_x0 + 2, fpc_x + fpc_w / 2 + 6]) translate([x, pan_y0 - c - rw, 0]) cube([min(30, fpc_x - fpc_w / 2 - 6 - pan_x0 - 2), rw, rh]);
  }
}

// ---------- back cover (modelled in place) ----------
module back_cover() {
  difference() {
    union() {
      translate([0, 0, T]) mirror([0, 0, 1]) translate([0, 0, 0]) chamfered_slab(0, back_t, back_chamfer);
      for (s = [-1, 1]) translate([W / 2 + s * kh_dx - 8, kh_y - 6.5, inner_back - 4 + eps]) cube([16, 23, 4]);
      if (custom) custom_cover_inside();
      else {
        board_clips();
        translate([adp_x - 1, adp_y - 1, inner_back - adp_pad_h + eps]) cube([adp_w + 2, adp_h + 2, adp_pad_h]);   // tape pad for DESPI-C02
      }
    }
    if (custom) {
      ports();
      for (r = [[module2[0] - 1, module2[1] - 1, module2[2] + 2, module2[3] + 2], [wall, usbc_y - 6, 12, 12]])
        translate([r[0], r[1], inner_back - eps]) cube([r[2], r[3], pocket_d]);   // pockets over the module and USB-C
    }
    for (p = boss_pts) translate([p[0], p[1], inner_back - 1]) {
      cylinder(d = clear_d, h = back_t + 2);
      translate([0, 0, back_t + 1 - 1.4]) cylinder(d1 = clear_d, d2 = 5.6, h = 1.4 + eps);
    }
    for (s = [-1, 1]) translate([W / 2 + s * kh_dx, 0, 0]) {
      translate([0, kh_y, inner_back - 1]) cylinder(d = kh_d, h = back_t + 2);
      hull() for (dy = [0, kh_len]) translate([0, kh_y + dy, inner_back - 1]) cylinder(d = kh_slot, h = back_t + 2);
      hull() for (dy = [0, kh_len]) translate([0, kh_y + dy, inner_back - 3]) cylinder(d = kh_d + 0.5, h = 3 + eps);
    }
    // vent slots over the board (over the charger and the regulator on the custom board)
    if (custom) for (i = [0 : 3]) translate([18 + i * 8, 20, inner_back - 1]) hull() for (dy = [0, 20]) translate([0, dy, 0]) cylinder(d = 2.4, h = back_t + 2);
    else for (i = [0 : 5]) translate([board_x + 12 + i * 8, board_y + 12, inner_back - 1]) hull() for (dy = [0, 30]) translate([0, dy, 0]) cylinder(d = 2.4, h = back_t + 2);
  }
}

// the side openings for USB-C and the power switch; on the custom board they reach the back edge
module ports() {
  side_hole(usbc_y, usbc_z, custom ? usb2_open : usbc_open);
  side_hole(switch_y, switch_z, custom ? sw2_open : switch_open);
  if (custom) translate([-1, usbc_y - usb2_open[0] / 2, usbc_z]) cube([wall + 4, usb2_open[0], T]);
}

// custom board: a fence keeps the battery in place, posts keep the board on the switches
module custom_cover_inside() {
  bx = battery2[0];  by = battery2[1];  bw = battery2[2];  bh = battery2[3];
  fence = inner_back - (front_t + tape_t + pan_t + 0.5) - battery2[4];   // the battery lies on the cover
  difference() {
    translate([bx - 1.2, by - 1.2, inner_back - 2.5 + eps]) cube([bw + 2.4, bh + 2.4, 2.5]);
    translate([bx, by, inner_back - 3]) cube([bw, bh, 4]);
    translate([bx + 36, by - 2, inner_back - 3]) cube([10, 4, 4]);         // gap for the battery leads, over the board pads
  }
  for (g = [1.5, 3.5, 5.5]) translate([kx(g), 13, pcb2_back + 0.3]) cylinder(d = 4, h = inner_back - pcb2_back - 0.3 + eps);
}

// clips hold the board by its long edges (headers removed); a backstop takes the plug force
module board_clips() {
  post_l = inner_back - board_comp_z;              // cover -> component face
  for (bx = [8, board_w - 8], side = [0, 1]) {
    y = side == 0 ? board_y - 1.6 : board_y + board_h + 0.2;
    translate([board_x + bx - 3, y, board_comp_z]) {
      cube([6, 1.4, post_l + eps]);                                         // flexing post
      translate([0, side == 0 ? 0 : -1.0, -pcb_t - 0.9]) cube([6, 2.4, 0.9]);   // hook over the solder face
      translate([0, side == 0 ? 0 : 0, -pcb_t]) cube([6, 1.4, pcb_t + eps]);
    }
  }
  // backstop behind the far edge
  translate([board_x + board_w + 0.2, board_y + 12, board_sold_z]) cube([2, 30, inner_back - board_sold_z + eps]);
}

// ---------- keycap (print orientation: top face on the bed, legs up) ----------
module keycap(dimple = false) {
  difference() {
    union() {
      difference() {
        hull() {
          linear_extrude(eps) offset(-0.6) stadium(pill_w, pill_h);
          translate([0, 0, 0.6]) linear_extrude(cap_t - 0.6) stadium(pill_w, pill_h);
        }
        translate([-7.8, -pill_h, cap_t - cap_recess]) cube([15.6, 2 * pill_h, cap_recess + 1]);   // clears the housing at bottom-out
      }
      for (sx = [-stem_dx / 2, stem_dx / 2]) translate([sx - stem_w / 2, -stem_l / 2, cap_t - cap_recess - eps]) cube([stem_w, stem_l, stem_h]);
    }
    if (dimple) translate([0, 0, -8 + 0.7]) sphere(r = 8, $fn = 96);
  }
}

// ---------- rear desk leg (device coordinates, sits on the back face z = T) ----------
// Two screws go into the bar from the device side with their heads 2.8 mm proud; the heads
// drop into the wall keyholes and the device's weight pushes them to the top of the slots.
// The body stands on its bottom edge and leans back on the fin.
lock_y = kh_y + kh_len;                           // screw position when locked
function desk_s(n) = n / tan(90 - tilt);          // desk line: height on the back face for a given distance out
module leg() {
  translate([0, 0, T]) difference() {
    union() {
      // cross bar, rounded
      translate([W / 2, lock_y, 0]) linear_extrude(leg_bar[2]) offset(r = 4) offset(delta = -4) square([leg_bar[0], leg_bar[1]], center = true);
      // fin in the (y = height on the back, z = distance out) plane
      translate([W / 2 - leg_t / 2, 0, 0]) rotate([90, 0, 90]) linear_extrude(leg_t)
        offset(r = 3) offset(delta = -3)
          polygon([[leg_contact[0], 0], [leg_contact[1], 0], [desk_s(leg_foot[1]), leg_foot[1]], [desk_s(leg_foot[0]), leg_foot[0]]]);
    }
    for (sx = [-1, 1]) translate([W / 2 + sx * kh_dx, lock_y, -1]) cylinder(d = screw_pilot, h = leg_bar[2] - 1);
    // cut the foot flat along the desk
    rotate([-tilt, 0, 0]) translate([-1, -200, -50]) cube([W + 2, 200, 250]);
  }
}
// print orientation: cap on the bed, stem up
module peg() {
  difference() {
    union() {
      hull() { cylinder(d = peg_cap[0] - 1, h = eps); translate([0, 0, 0.5]) cylinder(d = peg_cap[0], h = peg_cap[1] - 0.5); }   // chamfer leads it into the hole
      cylinder(d = peg_neck, h = peg_cap[1] + screw_gap);
      translate([0, 0, peg_cap[1] + screw_gap - eps]) cylinder(d1 = peg_stem[0], d2 = peg_stem[0] - 0.3, h = peg_stem[1]);   // slight taper starts it in the hole
    }
    translate([peg_stem[0] / 2 - 0.4, -0.3, peg_cap[1] + screw_gap]) cube([1, 0.6, peg_stem[1] + 1]);   // vent: lets air and extra glue out
  }
}
module leg_pegs() {
  for (sx = [-1, 1]) color("#b0b0b0") translate([W / 2 + sx * kh_dx, lock_y, T - screw_gap - peg_cap[1]]) peg();
}

// ---------- wall mount (device coordinates, sits on the back face z = T, wall at z = T + mount_t) ----------
// Taped to the wall; the body's keyholes drop over its pegs and slide down to lock, like on the leg.
// The bar top stays 2 mm under the body's top edge, so nothing shows from the front.
module mount_outline() {
  offset(r = 4) offset(delta = -4) offset(r = -8) offset(delta = 8) union() {
    translate([W / 2, lock_y]) square(mount_bar, center = true);
    translate([W / 2 - mount_stem[0] / 2, mount_stem[1]]) square([mount_stem[0], lock_y - mount_stem[1]]);
  }
}
// Peg grown out of the plate (plate face at z = 0, pointing +z, as it prints): same neck and cap as `peg`,
// but under the cap a 0.5 mm ledge takes the slot edge and a 45° cone carries the rest, so it prints without supports.
module mount_peg() {
  g = screw_gap;  h = g + peg_cap[1];  rn = peg_neck / 2;  rc = peg_cap[0] / 2;
  rotate_extrude() polygon([[0, 0], [rn + 0.2, 0], [rn, 0.4], [rn, g], [rn + 0.5, g], [rc, g + rc - rn - 0.5],
                            [rc, h - 0.4], [rc - 0.4, h], [0, h]]);
}
module wall_mount() {
  c = mount_chamfer;
  translate([0, 0, T]) {
    difference() {
      minkowski() {
        translate([0, 0, c]) linear_extrude(mount_t - 2 * c) offset(-c) mount_outline();
        union() { translate([0, 0, -c]) cylinder(r1 = 0, r2 = c, h = c, $fn = 16); cylinder(r1 = c, r2 = 0, h = c, $fn = 16); }
      }
      // centre notches at the top and the bottom: line them up with a plumb pencil mark
      for (y = [lock_y + mount_bar[1] / 2, mount_stem[1]]) translate([W / 2, y, mount_t / 2]) rotate(45) cube([2.5, 2.5, mount_t + 2], center = true);
    }
    for (sx = [-1, 1]) translate([W / 2 + sx * kh_dx, lock_y, eps]) mirror([0, 0, 1]) mount_peg();
  }
}

// ---------- switch plate (print flat) ----------
module key_plate(keys = [0 : n_keys - 1], x0 = act_x0 - 1, w = act_w + 2) {
  translate([0, 0, plate_z0]) difference() {
    union() {
      translate([x0, wall + 0.3, 0]) cube([w, key_block_y1 - wall - 0.6, plate_t]);
      // pads under the screw heads (clipped to the plate outline)
      intersection() {
        for (g = plate_screws) if (kx(g) > x0 && kx(g) < x0 + w) translate([kx(g), plate_screw_y, plate_t - eps]) cylinder(d = plate_boss_d, h = plate_boss_h + eps);
        translate([x0, wall + 0.3, 0]) cube([w, key_block_y1 - wall - 0.6, plate_t + plate_boss_h + 1]);
      }
    }
    for (i = keys) translate([kx(i) - choc_cut / 2, key_cy - choc_cut / 2, -1]) cube([choc_cut, choc_cut, plate_t + 2]);
    for (g = plate_screws) translate([kx(g), plate_screw_y, -1]) cylinder(d = screw_clear, h = plate_t + plate_boss_h + 2);
  }
}

module key_test() {
  x0 = kx(1) - pitch / 2 - 2;  w = 2 * pitch + 4;
  intersection() {
    front_shell();
    translate([x0, 0, 0]) cube([w, key_block_y1 + 6, key_block_d + 2]);
  }
  translate([0, key_block_y1 + 12, -plate_z0]) key_plate([0, 1], x0, w);   // plate coupon, flat on the bed
}

// ---------- preview dummies ----------
module panel_dummy() {
  color("#f2f1ec") translate([pan_x0, pan_y0, front_t + tape_t]) cube([pan_w, pan_h, pan_t]);
  color("#c8a24a") translate([fpc_x - fpc_w / 2, pan_y0 - 2.5, front_t + tape_t + pan_t]) cube([fpc_w, 2.5, 0.2]);
  color("#c8a24a") translate([fpc_x - fpc_w / 2, pan_y0 - 2.5, front_t + tape_t + pan_t + 0.2]) cube([fpc_w, 0.2, 2.5]);
}
module board_dummy() {
  if (custom) custom_board_dummy(); else esp32l_dummy();
}
module custom_board_dummy() {
  color("#1f6b3a") translate([0, 0, pcb2_z]) linear_extrude(pcb_t) difference() {
    translate([pcb2[0], pcb2[1]]) square([pcb2[2] - pcb2[0], pcb2[3] - pcb2[1]]);
    translate([pcb2_slot[0], pcb2_slot[1]]) square([pcb2_slot[2] - pcb2_slot[0], pcb2_slot[3] - pcb2_slot[1]]);
  }
  color("#1a1a1a") translate([module2[0], module2[1], pcb2_back]) cube([module2[2], module2[3], 3.2]);
  color("#cfcfcf") translate([pcb2[0], usbc_y - 4.5, pcb2_back]) cube([7.3, 9, 3.2]);
  color("#3b4a8c") translate([battery2[0], battery2[1], inner_back - battery2[4]]) cube([battery2[2] - 0.5, battery2[3] - 0.5, battery2[4]]);
}
module esp32l_dummy() {
  color("#245aa8") translate([board_x, board_y, board_sold_z]) cube([board_w, board_h, pcb_t]);
  color("#cfcfcf") translate([board_x - 0.5, usbc_y - 4.5, board_comp_z]) cube([7.5, 9, 3.2]);
  color("#1a1a1a") translate([board_x + 30, board_y + 18, board_comp_z]) cube([18, 25.5, 3.1]);
  color("#245aa8") translate([adp_x, adp_y, inner_back - adp_pad_h - pcb_t]) cube([adp_w, adp_h, pcb_t]);
}
module switches_dummy() {
  for (i = [0 : n_keys - 1]) translate([kx(i), key_cy, 0]) {
    color("#7a5a3a") translate([-7.5, -7.5, plate_z0 - house_above_plate]) cube([15, 15, house_above_plate]);
    color("#7a5a3a") translate([-6.8, -6.8, plate_z0 + plate_t]) cube([13.6, 13.6, below_plate]);
  }
}
module caps_in_place() {
  for (i = [0 : n_keys - 1]) color("#2a2a28") translate([kx(i), key_cy, -cap_protrude]) keycap(i == 0);   // print orientation already has the top at z = 0, legs inward
}
module device(back = true) {
  color("#3a3a38") front_shell();
  if (back) color("#353533") back_cover();
  color("#5a5a56") key_plate();
  panel_dummy(); board_dummy(); switches_dummy(); caps_in_place();
}
module to_world() { translate([W, 0, 0]) rotate([0, 0, 180]) rotate([90, 0, 0]) children(); }

// ---------- part selector ----------
if (part == "front") front_shell();
else if (part == "back") translate([0, H, T]) rotate([180, 0, 0]) back_cover();
else if (part == "leg") translate([0, 0, -T]) leg();
else if (part == "peg") for (i = [0, 1]) translate([i * (peg_cap[0] + 4), 0, 0]) peg();
else if (part == "key_plate") translate([0, 0, -plate_z0]) key_plate();
else if (part == "keycap") keycap(false);
else if (part == "keycap_dimple") keycap(true);
else if (part == "key_test") key_test();
else if (part == "wall_mount") translate([0, 0, T + mount_t]) mirror([0, 0, 1]) wall_mount();
else if (part == "assembly_wall") to_world() { device(); color("#6a6a64") wall_mount(); }
else if (part == "assembly_back") to_world() device();
else if (part == "assembly_open") device(false);
else if (part == "exploded") to_world() {
  translate([0, 0, -25]) caps_in_place();
  color("#4a4a47") front_shell();
  translate([0, 0, 25]) panel_dummy();
  translate([0, 0, 50]) { color("#8a8a84") key_plate(); switches_dummy(); }
  translate([0, 0, 80]) board_dummy();
  translate([0, 0, 115]) color("#55554f") back_cover();
}
else {   // on the desk: leaning back on the leg, pivoting on the back-bottom edge
  to_world() translate([0, 0, T]) rotate([tilt, 0, 0]) translate([0, 0, -T]) {
    device(); color("#3a3a38") leg(); leg_pegs();
  }
  if (part == "assembly_side") color("#cfcbbf") translate([-40, -60, -1]) cube([W + 80, 200, 1]);
}
