"""Generate ICEM Tcl replay, export through its standalone Fluent converter,
then audit the mesh with Fluent 242. ICEM installation is selected explicitly.
"""
import os
import json
import hashlib
from pathlib import Path
import subprocess
import time
from mesh_backend import write_json, launch, face_quality, cell_quality, checked_mesh, generated_boundary_ids
from inventory import inspect_scdoc
from quality import assess


def tcl_path(path):
    value = str(Path(path).resolve()).replace('\\', '/')
    if any(char in value for char in '{}\n\r'):
        raise ValueError('ICEM paths cannot contain braces or line breaks')
    return '{' + value + '}'


def generate_replay(source, output, config):
    if config.get('icem_method') == 'hexa':
        from icem_structured import generate_hex_replay
        return generate_hex_replay(source, output, config)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Values are validated numbers; file paths are Tcl braced literals.
    script = '''# Generated for ANSYS ICEM CFD 2024 R2. Units: mm.
set output @OUTPUT@
file mkdir $output
cd $output
set status [open status.txt w]
if {[catch {
    if {![ic_check_licensing_aienv]} {error "ICEM_LICENSE_UNAVAILABLE"}
    ic_wb_set_default_properties
    ic_set_global vid_options 1 wb_import_sel_proc
    ic_set_global vid_options {} wb_import_sel_pre
    ic_set_global vid_options 1 wb_NS_to_entity_parts
    ic_set_global vid_options 1 wb_import_mat_points
    ic_set_global vid_options millimeters wb_import_scale_geo
    ic_wb_brep_read @SOURCE@ 1 0 0 0 1 0 1 0 {} 1 0 0 1
    set units [ic_geo_get_units 1]
    if {$units == ""} {error "Imported geometry has no declared length unit"}
    set factor [ic_geo_convert_units $units millimeters]
    if {$factor <= 0} {error "Unsupported imported length unit: $units"}
    if {$factor != 1.0} {
        foreach type {point curve surface material density} {
            set entities [ic_geo_get_objects $type]
            if {[llength $entities] > 0} {
                ic_move_geometry $type names $entities scale "$factor $factor $factor" cent {0 0 0} detach 0
            }
        }
        ic_geo_set_units millimeters
        ic_geo_reset_data_structures
    }
    if {[ic_geo_get_units] != "mm"} {error "Geometry unit normalization failed"}
    set surfaces [ic_geo_get_objects surface]
    if {[llength $surfaces] == 0} {error "No imported surfaces"}
    set materials [ic_geo_get_objects material]
    if {[llength $materials] == 0} {error "No fluid material point; refusing an unclassified volume"}
    set families [ic_geo_list_families]
    set fluidfamilies {}
    foreach fam $families {
        if {[string match -nocase fluid_* $fam]} {lappend fluidfamilies $fam}
    }
    if {[llength $fluidfamilies] != 1 || [llength $materials] != 1} {
        error "This workflow requires exactly one named fluid domain and one material point"
    }
    ic_geo_set_family material [lindex $fluidfamilies 0] names $materials
    puts $status "families=$families"
    flush $status
    ic_set_meshing_params global 0 gref @MAX@ gmax @MAX@ grat @GROWTH@ gfast 0
    foreach surf $surfaces {
        ic_set_meshing_params surface $surf emax @MAX@ emin @MIN@
    }
    set wallfamilies {}
    foreach fam $families {
        if {[string match -nocase *wall* $fam] || [string match -nocase *upface $fam] || [string match -nocase *downface $fam]} {
            lappend wallfamilies $fam
            ic_geo_set_family_params $fam height @HEIGHT@ hrat @LAYER_GROWTH@ nlay @LAYERS@
        }
    }
    set geometry [file join $output geometry.tin]
    set tetra [file join $output tetra.uns]
    ic_save_tetin $geometry
    if {![ic_run_tetra $geometry $tetra run_cutter 1 run_smoother 1 n_processors @CORES@ log tetra.log]} {
        error "Tetra mesher failed"
    }
    set mesh $tetra
    if {@LAYERS@ > 0} {
        if {[llength $wallfamilies] == 0} {error "No named wall parts for prism layers"}
        set mesh [file join $output prism.uns]
        # Explicit params avoids the undefined ifile cleanup path in 221.
        set prismoptions [list params [file join $output prism_params.txt] layers @LAYERS@ height @HEIGHT@ ratio @LAYER_GROWTH@ log prism.log]
        foreach fam $wallfamilies {lappend prismoptions family $fam}
        if {![eval [linsert $prismoptions 0 ic_run_prism $geometry $tetra $mesh]]} {error "Prism mesher failed"}
    }
    ic_load_unstruct $mesh
    ic_boco_save mesh.fbc
    # Avoid solution_input GUI callbacks, which crash med_batch on ICEM 221.
    set converter @CONVERTER@
    exec $converter -dom $mesh -b [file join $output mesh.fbc] -bin [file join $output mesh.msh] > export.log 2>@1
    if {![file exists mesh.msh] || [file size mesh.msh] == 0} {error "Fluent mesh export missing"}
    puts $status SUCCESS
} message]} {
    puts $status "ERROR: $message"
    if {[info exists ::errorInfo]} {puts $status $::errorInfo}
    close $status
    exit 2
}
close $status
exit 0
'''
    replacements = {'CONVERTER': tcl_path(Path(config['icem_root']) / 'icemcfd/win64_amd/icemcfd/output-interfaces/fluent6.exe'),
                    'OUTPUT': tcl_path(output), 'SOURCE': tcl_path(source), 'MAX': config['max_size'],
                    'MIN': config['min_size'], 'GROWTH': config['growth_rate'], 'HEIGHT': config['first_height'],
                    'LAYER_GROWTH': config['layer_growth'], 'LAYERS': config['boundary_layers'], 'CORES': config['cores']}
    for key, value in replacements.items():
        script = script.replace('@' + key + '@', str(value))
    path = output / 'mesh.rpl'
    path.write_text(script, encoding='utf-8')
    return path


def icem_mesh(source, output, config):
    output = Path(output).resolve()
    replay = generate_replay(source, output, config)
    write_json(output / 'parameters.json', config)
    root = Path(config['icem_root'])
    result = {'model': source.stem, 'backend': 'icem', 'icem_version': root.name,
              'passed': False, 'status': 'running', 'mesh_unit': 'mm',
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    start = time.monotonic()
    try:
        env = dict(os.environ, AWP_ROOT=str(root))
        env['AWP_ROOT' + root.name.lstrip('v')] = str(root)
        with (output / 'icem.log').open('w', encoding='utf-8') as log:
            completed = subprocess.run([str(root / 'icemcfd/win64_amd/bin/icemcfd.bat'), '-batch', '-script', str(replay)],
                           cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT,
                           timeout=config['timeout_seconds'], check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        log_text = (output / 'icem.log').read_text(encoding='utf-8', errors='replace')
        if 'FlexNet Licensing error' in log_text or 'proper license key' in log_text:
            result['status'] = 'license_blocked'
            raise RuntimeError('ICEM ' + root.name + ' license unavailable; see icem.log')
        completed.check_returncode()
        status_path = output / 'status.txt'
        if not status_path.exists() or 'SUCCESS' not in status_path.read_text(errors='replace'):
            raise RuntimeError('ICEM did not report successful mesh export; see icem.log/status.txt')
        if config.get('icem_method') == 'hexa':
            counts = json.loads((output / 'element_counts.json').read_text())
            if counts.get('HEXA_8', 0) <= 0 or any(counts.get(k, -1) != 0 for k in ('TETRA_4', 'PENTA_6', 'PYRA_5')):
                raise RuntimeError('Structured replay did not produce pure hexahedra')
            result['element_counts'] = counts
            result['icem_method'] = 'hexa_template'
            from mesh_connectivity import audit
            connectivity = audit(output / 'mesh_ascii.msh')
            if connectivity['cells'] != counts['HEXA_8']:
                raise RuntimeError('Connectivity export cell count differs from pure-hexa count')
            result['connectivity'] = connectivity
            write_json(output / 'connectivity_audit.json', connectivity)
        mesh = output / 'mesh.msh'
        session = launch(output, config)
        try:
            session.tui.file.read_mesh(mesh.as_posix())
            util = session.meshing_utilities
            ids = generated_boundary_ids(session)
            names = list(util.convert_zone_ids_to_name_strings(zone_id_list=ids))
            skew, detail = face_quality(session, ids)
            cell = cell_quality(session)
            if config.get('icem_method') == 'hexa' and cell['count'] != result['element_counts']['HEXA_8']:
                raise RuntimeError('Exported cell count differs from pure-hexa count')
            expected = [g['name'] for g in inspect_scdoc(source)['groups'] if not g['name'].startswith('fluid_')]
            actual = [name.lower() for name in names]
            named_ok = all(any(prefix + name.lower() in actual for prefix in ('', 'zone', 'fam')) for name in expected)
            if config.get('icem_method') == 'hexa':
                allowed = {prefix + name.lower() for name in expected for prefix in ('', 'zone', 'fam')}
                named_ok = named_ok and all(name in allowed for name in actual)
            check_ok = checked_mesh(session, output)
            result.update(assess(skew, cell['min'], cells=cell['count'], mesh_check_ok=check_ok,
                                 named_boundaries_ok=named_ok, surface_limit=config['surface_limit'], enforce_surface_limit=config.get('enforce_surface_limit', True),
                                 orthogonal_limit=config['orthogonal_limit'], orthogonal_strict=config['orthogonal_strict']))
            if config.get('icem_method') == 'hexa':
                if not result['connectivity']['single_connected_volume']:
                    result['passed'] = False
                    result['failures'].append('Fluid mesh contains disconnected cell components')
                from icem_structured import compare_volume
                evidence = json.loads((output / 'template_evidence.json').read_text())
                result.update(compare_volume((output / 'mesh_check.txt').read_text(), evidence['cad_volume_mm3'], config.get('icem_hex_volume_tolerance', 0.01)))
                if not result['volume_match_ok']:
                    result['passed'] = False
                    result['failures'].append('Mesh volume differs from source CAD fluid volume')
            result.update({'mesh_file': 'mesh.msh', 'mesh_check_ok': check_ok, 'named_boundaries_ok': named_ok,
                           'mesh_sha256': hashlib.sha256(mesh.read_bytes()).hexdigest(),
                           'thresholds': {'enforce_surface_limit': config.get('enforce_surface_limit', True), 'surface_limit': config['surface_limit'], 'orthogonal_limit': config['orthogonal_limit'], 'orthogonal_strict': config['orthogonal_strict']},
                           'final_boundary_zones': detail, 'status': 'passed' if result['passed'] else 'quality_not_met'})
        finally:
            session.exit(timeout=10, wait=5)
        return result
    except Exception as error:
        if result['status'] == 'running':
            result['status'] = 'error'
        result['error'] = str(error)
        raise
    finally:
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        write_json(output / 'quality.json', result)
