$fn=60;
difference() {
    cube([58, 82, 2]);
    translate([29, 40, -0.5])
        mirror([1,0,0])
            linear_extrude(height=1.5)
                text("Site Eye", size=4, font="Liberation Sans:style=Bold", halign="center", valign="center");
}
