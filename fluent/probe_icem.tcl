# ANSYS ICEM CFD 2024 R2 batch probe. No GUI or source CAD modification.
set out $env(PUMP_ICEM_OUTPUT)
file mkdir $out
cd $out
set report [open [file join $out probe.txt] w]
if {[catch {
    ic_wb_set_default_properties
    ic_set_global vid_options 1 wb_import_sel_proc
    ic_set_global vid_options {} wb_import_sel_pre
    ic_set_global vid_options 1 wb_NS_to_entity_parts
    ic_set_global vid_options 1 wb_import_mat_points
    ic_set_global vid_options millimeter wb_import_scale_geo
    ic_wb_brep_read $env(PUMP_INPUT) 1 0 0 0 1 0 1 0 {} 1 0 0 1
    puts $report "surfaces=[ic_geo_get_objects surface]"
    puts $report "materials=[ic_geo_get_objects material]"
    puts $report "families=[ic_geo_list_families]"
    ic_save_tetin [file join $out geometry.tin]
} message]} {
    puts $report "ERROR: $message"
    puts $report $errorInfo
}
close $report
exit
