// === SITE EYE CASE — v6 ===
// Full redesign per Michael's 13-point review 2026-03-17
//
// ORIENTATION:
//   FRONT = camera side (speaker vent, mic hole, camera lens, labels)
//   BACK  = OLED side (screen window, tactile buttons, Pi mounts)
//   TOP   = lanyard loop end
//   BOTTOM = micro-USB access
//
// Each shell: z=0 is outer face, +Z goes into case interior.
// Print each face-down (outer face on bed).
//
// LAYOUT (front face, Y=0 bottom, Y=82 top):
//   Y 8-28:  Speaker vent slots (speaker cradle behind)
//   Y 36:    Camera lens
//   Y 48-52: "Site Eye" / "Prototype v1" labels
//   Y 65:    Microphone vent (mic cradle behind)
//   Y 74-82: Lanyard loop at top
//
// LAYOUT (back face):
//   Y ~55:   OLED (centered upper area)
//   Y ~25:   Tactile buttons (below OLED, replacing removed back vents)
//   Y center: Pi Zero 2W standoffs
//
// REV LOG:
//   1. Labels mirrored for correct exterior reading
//   2. Labels on camera (front) side, smaller font
//   3. Camera moved down ~3/4" (19mm); speaker vent lowered
//   4. OLED mounts corrected: 30mm c-c, 3mm holes, 35.5x33.5 module, 34x18.5 screen
//   5. Assembled depth 34mm (30mm+ internal clearance)
//   6. Front mic opening added
//   7. Side micro-USB: 10mm deep x 20mm wide, 15mm from top
//   8. Bottom: single centered opening for micro-USB access (no per-shell holes)
//   9. 36mm speaker cradle behind front vent
//  10. 14mm mic cradle behind front mic opening
//  11. Single inset lanyard loop at top (replaces dual holes)
//  12. Pi Zero 2W inset screw holes: 23mm x 58mm c-c, centered on back plate
//  13. Two tactile button cutouts on back below OLED (back vents removed)

$fn = 60;

// --- Overall ---
case_w   = 58;
case_h   = 82;
case_d   = 34;       // assembled depth: 16+18 = 34mm
corner_r = 4;
wall     = 2;

// --- Shell split ---
front_d = 16;
back_d  = 18;

// --- Tolerances ---
tol   = 0.3;
lip   = 1.5;
lip_t = 1.2;

// ===== FRONT FACE FEATURES =====

// Speaker (36mm dia)
spk_dia        = 36;
spk_cradle_h   = 3;
spk_x          = case_w / 2;
spk_y          = 18;       // lower area
spk_vent_w     = 28;
spk_vent_h     = 1.5;
spk_vent_gap   = 3;
spk_vent_count = 4;

// Camera (moved down per #3)
cam_dia = 8;
cam_x   = case_w / 2;
cam_y   = 36;

// Labels (smaller per #2, between camera and mic)
label_size  = 4;
label_depth = 0.6;
label_y     = 50;
sub_size    = 2.5;
sub_label_y = 45;

// Microphone (14mm dia)
mic_dia      = 14;
mic_cradle_h = 3;
mic_x        = case_w / 2;
mic_y        = 65;
mic_vent_dia = 3;

// ===== BACK FACE FEATURES =====

// OLED (Inland 1.3" V2.0 — corrected per #4)
oled_mod_w    = 35.5;
oled_mod_h    = 33.5;
oled_scr_w    = 34;
oled_scr_h    = 18.5;
oled_hole_cc  = 30;      // horizontal center-to-center
oled_hole_dia = 3;
oled_cx       = case_w / 2;
oled_cy       = case_h - 10 - oled_mod_h / 2;  // upper area

// Tactile buttons (back, below OLED, per #13)
btn_w       = 7;        // cutout width
btn_h       = 7;        // cutout height
btn_spacing = 16;       // center-to-center horizontal
btn_y       = oled_cy - oled_mod_h/2 - 12;  // below OLED module

// Pi Zero 2W (corrected per #12)
pi_cc_w       = 23;      // c-c wide
pi_cc_l       = 58;      // c-c long
pi_standoff_h = 4;
pi_standoff_d = 5;
pi_hole_dia   = 2.75;    // M2.5 + clearance
pi_cx         = case_w / 2;
pi_cy         = case_h / 2;

// Side micro-USB (#7: 10mm deep x 20mm wide, 15mm from top)
usb_side_w    = 20;
usb_side_h    = 10;
usb_from_top  = 15;

// Bottom micro-USB access (#8: centered)
btm_usb_w = 15;
btm_usb_h = 8;

// Lanyard loop (#11: single inset loop)
loop_w      = 12;
loop_h      = 6;
loop_thick  = 3;
loop_hole_d = 3.5;

// =============================================
module rbox(w, h, d, r) {
    hull() {
        for (x = [r, w-r], y = [r, h-r])
            translate([x, y, 0])
                cylinder(r=r, h=d);
    }
}

// =============================================
// FRONT SHELL (camera/speaker/mic side)
// =============================================
module front_shell() {
    difference() {
        union() {
            // Shell body
            rbox(case_w, case_h, front_d, corner_r);

            // Interlocking lip
            translate([wall + tol, wall + tol, front_d - 0.01])
                difference() {
                    rbox(case_w - 2*(wall+tol), case_h - 2*(wall+tol),
                         lip, max(corner_r - wall, 0.5));
                    translate([lip_t, lip_t, -0.1])
                        rbox(case_w - 2*(wall+tol) - 2*lip_t,
                             case_h - 2*(wall+tol) - 2*lip_t,
                             lip + 0.2, max(corner_r - wall - lip_t, 0.5));
                }

            // Lanyard loop (#11 — solid tab protruding from top, overlaps 5mm into shell)
            translate([case_w/2 - loop_w/2, case_h - 5, 0])
                difference() {
                    cube([loop_w, 5 + loop_h, loop_thick]);
                    translate([loop_w/2, 5 + loop_h/2, -0.1])
                        cylinder(d=loop_hole_d, h=loop_thick + 0.2, $fn=24);
                }
        }

        // Hollow interior
        translate([wall, wall, wall])
            rbox(case_w - 2*wall, case_h - 2*wall, front_d,
                 max(corner_r - wall, 0.5));

        // Camera lens (#3)
        translate([cam_x, cam_y, -0.1])
            cylinder(d=cam_dia, h=wall + 0.2);

        // Speaker vent slots (#9)
        for (i = [0:spk_vent_count-1]) {
            vy = spk_y - ((spk_vent_count-1) * (spk_vent_h + spk_vent_gap)) / 2
                 + i * (spk_vent_h + spk_vent_gap);
            translate([(case_w - spk_vent_w)/2, vy, -0.1])
                cube([spk_vent_w, spk_vent_h, wall + 0.2]);
        }

        // Mic vent (#6)
        translate([mic_x, mic_y, -0.1])
            cylinder(d=mic_vent_dia, h=wall + 0.2);

        // Side micro-USB (#7 — through right wall)
        translate([case_w - wall - 0.1,
                   case_h - usb_from_top - usb_side_w,
                   wall])
            cube([wall + 0.2, usb_side_w, usb_side_h]);

        // Bottom micro-USB access (#8 — through bottom wall, centered)
        translate([(case_w - btm_usb_w)/2, -0.1, wall])
            cube([btm_usb_w, wall + 0.2, btm_usb_h]);
    }

    // --- Interior features (added after difference) ---

    // Speaker cradle (#9 — 36mm ring)
    translate([spk_x, spk_y, wall])
        difference() {
            cylinder(d=spk_dia + 3, h=spk_cradle_h);
            translate([0, 0, -0.1])
                cylinder(d=spk_dia, h=spk_cradle_h + 0.2);
        }

    // Mic cradle (#10 — 14mm ring)
    translate([mic_x, mic_y, wall])
        difference() {
            cylinder(d=mic_dia + 3, h=mic_cradle_h);
            translate([0, 0, -0.1])
                cylinder(d=mic_dia, h=mic_cradle_h + 0.2);
        }
}

// Text engravings as separate module (combine after for cleaner CSG)
module front_text_cuts() {
    // "Site Eye" (#1 mirrored, #2 smaller on camera side)
    // offset(delta=0.01) prevents degenerate zero-area facets from text paths
    translate([case_w/2, label_y, -0.1])
        mirror([1, 0, 0])
            linear_extrude(height = label_depth + 0.2, convexity=4)
                offset(delta=0.01)
                    text("Site Eye", size=label_size,
                         font="Liberation Sans:style=Bold",
                         halign="center", valign="center");

    // "Prototype v1"
    translate([case_w/2, sub_label_y, -0.1])
        mirror([1, 0, 0])
            linear_extrude(height = label_depth + 0.2, convexity=4)
                offset(delta=0.01)
                    text("Prototype v1", size=sub_size,
                         font="Liberation Sans",
                         halign="center", valign="center");
}

module front_shell_final() {
    difference() {
        front_shell();
        front_text_cuts();
    }
}

// =============================================
// BACK SHELL (OLED / buttons / Pi side)
// No back vents (#13 — replaced by button cutouts)
// =============================================
module back_shell() {
    difference() {
        // Shell body
        rbox(case_w, case_h, back_d, corner_r);

        // Hollow interior
        translate([wall, wall, wall])
            rbox(case_w - 2*wall, case_h - 2*wall, back_d,
                 max(corner_r - wall, 0.5));

        // Lip recess
        translate([wall + tol, wall + tol, back_d - lip - 0.01])
            rbox(case_w - 2*(wall+tol), case_h - 2*(wall+tol),
                 lip + 0.1, max(corner_r - wall, 0.5));

        // OLED screen window (#4: 34 x 18.5mm)
        translate([oled_cx - oled_scr_w/2, oled_cy - oled_scr_h/2, -0.1])
            cube([oled_scr_w, oled_scr_h, wall + 0.2]);

        // OLED module recess (#4: 35.5 x 33.5mm, 0.5mm shallow step)
        translate([oled_cx - oled_mod_w/2, oled_cy - oled_mod_h/2, -0.1])
            cube([oled_mod_w, oled_mod_h, 0.6]);

        // Tactile button cutouts (#13 — two square openings below OLED)
        for (dx = [-btn_spacing/2, btn_spacing/2])
            translate([case_w/2 + dx - btn_w/2, btn_y - btn_h/2, -0.1])
                cube([btn_w, btn_h, wall + 0.2]);

        // Side micro-USB (#7)
        translate([case_w - wall - 0.1,
                   case_h - usb_from_top - usb_side_w,
                   wall])
            cube([wall + 0.2, usb_side_w, usb_side_h]);

        // Bottom micro-USB access (#8)
        translate([(case_w - btm_usb_w)/2, -0.1, wall])
            cube([btm_usb_w, wall + 0.2, btm_usb_h]);
    }

    // OLED mount posts (#4: 30mm c-c horizontal, 3mm holes)
    // Two posts on horizontal axis through OLED center
    for (dx = [-oled_hole_cc/2, oled_hole_cc/2])
        translate([oled_cx + dx, oled_cy, wall])
            difference() {
                cylinder(d=oled_hole_dia + 2.5, h=3);
                translate([0, 0, -0.1])
                    cylinder(d=oled_hole_dia, h=3.2);
            }

    // Pi Zero 2W standoffs (#12: 23mm x 58mm c-c, centered, inset screw holes)
    for (dx = [-pi_cc_w/2, pi_cc_w/2])
        for (dy = [-pi_cc_l/2, pi_cc_l/2])
            translate([pi_cx + dx, pi_cy + dy, wall])
                difference() {
                    cylinder(d=pi_standoff_d, h=pi_standoff_h);
                    translate([0, 0, 0.5])
                        cylinder(d=pi_hole_dia, h=pi_standoff_h);
                }
}

// =============================================
// RENDER — uncomment ONE for STL export
// =============================================

// Front shell (camera side):
// front_shell_final();

// Back shell (OLED side):
// back_shell();

// Assembly preview (exploded):
// translate([0, 0, back_d + 5]) front_shell_final();
// back_shell();
