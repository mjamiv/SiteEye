$fn = 60;
case_w = 58; case_h = 82; front_d = 16; corner_r = 4; wall = 2;
tol = 0.3; lip = 1.5; lip_t = 1.2;
module rbox(w, h, d, r) { hull() { for (x=[r,w-r], y=[r,h-r]) translate([x,y,0]) cylinder(r=r, h=d); } }

difference() {
    union() {
        rbox(case_w, case_h, front_d, corner_r);
        // lip
        translate([wall+tol, wall+tol, front_d-0.01])
            difference() {
                rbox(case_w-2*(wall+tol), case_h-2*(wall+tol), lip, max(corner_r-wall,0.5));
                translate([lip_t, lip_t, -0.1])
                    rbox(case_w-2*(wall+tol)-2*lip_t, case_h-2*(wall+tol)-2*lip_t, lip+0.2, max(corner_r-wall-lip_t,0.5));
            }
        // loop
        translate([case_w/2, case_h-2, 1.5])
            difference() {
                hull() {
                    cube([14, 4, 3], center=true);
                    translate([0, 8, 0]) rotate([0,90,0]) cylinder(d=3, h=14, center=true, $fn=30);
                }
                translate([0, 8, 0]) rotate([0,90,0]) cylinder(d=4, h=16, center=true, $fn=30);
            }
    }
    translate([wall, wall, wall]) rbox(case_w-2*wall, case_h-2*wall, front_d, max(corner_r-wall, 0.5));
}
