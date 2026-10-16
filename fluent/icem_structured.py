"""Replay a geometry-bound Hexa template; never invent blocking for an unknown CAD."""
import hashlib
import json
import math
import re
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


EDGE_PARAMETERS = {
    'start_spacing_mm': ('h1', 'sp1a'),
    'end_spacing_mm': ('h2', 'sp2a'),
    'start_growth': ('r1', 'r1a'),
    'end_growth': ('r2', 'r2a'),
    'max_spacing_mm': ('lmax', 'max'),
}


def resolve_distributions(groups, settings):
    """Canonicalize directed edge settings, including swapped endpoints."""
    if not isinstance(settings, dict) or set(settings) - set(groups):
        raise ValueError('Unknown edge distribution group')
    edges = {}
    for group, values in settings.items():
        if not isinstance(values, dict) or set(values) - set(EDGE_PARAMETERS):
            raise ValueError('Unknown edge distribution parameter')
        for name, value in values.items():
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('Edge distribution parameters must be positive finite numbers')
            if name.endswith('growth') and value < 1:
                raise ValueError('Growth ratios must be >=1')
        for a, b in groups[group]:
            oriented = dict(values)
            if a > b:
                oriented = {name.replace('start_', 'END_').replace('end_', 'start_').replace('END_', 'end_'): value
                            for name, value in values.items()}
            target = edges.setdefault(tuple(sorted((a, b))), {})
            for name, value in oriented.items():
                if name in target and target[name] != value:
                    raise ValueError('Conflicting distribution on shared blocking edge')
                target[name] = value
    return edges


def load_template(source, config):
    source = Path(source).resolve()
    manifests = config.get('icem_hex_templates', {})
    if source.stem not in manifests:
        raise ValueError('No verified ICEM blocking template for ' + source.stem)
    manifest_path = Path(manifests[source.stem]).resolve()
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    if data.get('source_sha256') != sha256(source):
        raise ValueError('Blocking template does not match source geometry fingerprint')
    if data.get('length_unit') != 'mm':
        raise ValueError('Blocking and geometry template coordinates must be millimetres')
    for name in ('geometry', 'blocking'):
        path = (manifest_path.parent / data[name]).resolve()
        if sha256(path) != data.get(name + '_sha256'):
            raise ValueError(name + ' template fingerprint mismatch')
        data[name] = path
    volume = data.get('cad_volume_mm3')
    if type(volume) not in (int, float) or not math.isfinite(volume) or volume <= 0:
        raise ValueError('Positive CAD fluid volume in mm3 required')
    families = data.get('fluid_families', [])
    if not families or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', x) for x in families):
        raise ValueError('Explicit valid fluid block families required')
    groups = data.get('edge_groups', {})
    counts = dict(data.get('node_counts', {}))
    overrides = config.get('icem_hex_node_counts', {})
    if set(overrides) - set(groups) or set(counts) != set(groups):
        raise ValueError('Every named edge group needs a node count; unknown overrides rejected')
    counts.update(overrides)
    edges = {}
    for group, pairs in groups.items():
        count = counts[group]
        if type(count) is not int or count < 2 or not pairs:
            raise ValueError('Nonempty edge group and integer node count >=2 required')
        for pair in pairs:
            if len(pair) != 2 or any(type(v) is not int or v < 0 for v in pair) or pair[0] == pair[1]:
                raise ValueError('Invalid blocking edge vertex pair')
            key = tuple(sorted(pair))
            if key in edges and edges[key] != count:
                raise ValueError('Conflicting node counts on shared blocking edge')
            edges[key] = count
    data['edge_counts'] = edges
    data['edge_distributions'] = resolve_distributions(groups, config.get('icem_hex_edge_parameters', {}))
    data['manifest_sha256'] = sha256(manifest_path)
    return data


def generate_hex_replay(source, output, config):
    from icem_backend import tcl_path
    data = load_template(source, config)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Query actual edge meshing parameters; curve segment counts are unrelated.
    set_edges = []
    check_edges = []
    for (a, b), count in sorted(data['edge_counts'].items()):
        parameters = data['edge_distributions'].get((a, b), {})
        suffix = ''.join(' %s %.17g' % (EDGE_PARAMETERS[name][0], value) for name, value in sorted(parameters.items()))
        set_edges.append('    ic_hex_set_mesh %d %d n %d%s' % (a, b, count, suffix))
        check_edges.append('    if {[ic_hex_get_edge_param %d %d nodes] != %d} {error "Edge node count mismatch: %d %d"}' % (a, b, count, a, b))
    readback = ['    set parameters_file [open edge_parameters.tsv w]', '    puts $parameters_file {vertex_a\tvertex_b\tparameter\tvalue}']
    for a, b in sorted(data['edge_counts']):
        for parameter in ('nodes', 'law', 'len', 'max', 'sp1a', 'sp2a', 'r1a', 'r2a'):
            readback.append('    puts $parameters_file \"%d\\t%d\\t%s\\t[ic_hex_get_edge_param %d %d %s]\"' % (a, b, parameter, a, b, parameter))
    readback.append('    close $parameters_file')
    script = r'''# ICEM Hexa template replay. Template owns CAD associations and distributions.
cd @OUTPUT@
set status [open status.txt w]
if {[catch {
    if {![ic_check_licensing_aienv]} {error "ICEM_LICENSE_UNAVAILABLE"}
    ic_load_tetin @GEOMETRY@
    if {[ic_geo_get_units] != "mm"} {error "Template CAD unit is not mm"}
    ic_hex_init
    ic_hex_restore_blocking @BLOCKING@
    if {![ic_hex_blocking_loaded]} {error "Blocking did not load"}
    if {[ic_hex_mesh_dimension] != 3} {error "Blocking is not three dimensional"}
    if {[ic_hex_count_unstruct_blocks 3d] != 0} {error "Unstructured blocks are forbidden"}
    set families {@FAMILIES@}
    set available [ic_hex_list_block_families]
    foreach fam $families {
        if {[lsearch -exact $available $fam] < 0} {error "Fluid blocking family missing: $fam"}
    }
@SET_EDGES@
    eval ic_hex_create_mesh $families proj 2 dim_to_mesh 3 nproc @CORES@
@CHECK_EDGES@
@READBACK@
    set mesh [file join [pwd] hexa.uns]
    eval ic_hex_write_file [list $mesh] $families proj 2 dim_to_mesh 3 no_boco
    ic_hex_save_blocking [file join [pwd] mesh.blk]
    ic_load_unstruct $mesh
    set countfile [open element_counts.json w]
    set hexes [ic_count_elements HEXA_8]
    set tets [ic_count_elements TETRA_4]
    set prisms [ic_count_elements PENTA_6]
    set pyramids [ic_count_elements PYRA_5]
    puts $countfile [format {"HEXA_8":%d,"TETRA_4":%d,"PENTA_6":%d,"PYRA_5":%d} $hexes $tets $prisms $pyramids]
    close $countfile
    if {$hexes <= 0 || $tets != 0 || $prisms != 0 || $pyramids != 0} {error "Mesh is not pure HEXA_8"}
    ic_boco_save mesh.fbc
    exec @CONVERTER@ -dom $mesh -b [file join [pwd] mesh.fbc] -bin [file join [pwd] mesh.msh] > export.log 2>@1
    exec @CONVERTER@ -dom $mesh -b [file join [pwd] mesh.fbc] [file join [pwd] mesh_ascii.msh] > export_ascii.log 2>@1
    if {![file exists mesh.msh] || [file size mesh.msh] == 0} {error "Fluent export missing"}
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
    # JSON braces must be data inside the Tcl format string.
    script = script.replace('format {"HEXA_8":', 'format {{"HEXA_8":').replace('"PYRA_5":%d} $hexes', '"PYRA_5":%d}} $hexes')
    replacements = {'OUTPUT': tcl_path(output), 'GEOMETRY': tcl_path(data['geometry']),
                    'BLOCKING': tcl_path(data['blocking']), 'FAMILIES': ' '.join(data['fluid_families']),
                    'CORES': str(config['cores']), 'SET_EDGES': '\n'.join(set_edges),
                    'CHECK_EDGES': '\n'.join(check_edges), 'READBACK': '\n'.join(readback),
                    'CONVERTER': tcl_path(Path(config['icem_root']) / 'icemcfd/win64_amd/icemcfd/output-interfaces/fluent6.exe')}
    for key, value in replacements.items():
        script = script.replace('@' + key + '@', value)
    replay = output / 'mesh.rpl'
    replay.write_text(script, encoding='utf-8')
    (output / 'template_evidence.json').write_text(json.dumps({
        'manifest_sha256': data['manifest_sha256'], 'source_sha256': data['source_sha256'],
        'cad_volume_mm3': data['cad_volume_mm3'],
        'geometry_sha256': data['geometry_sha256'], 'blocking_sha256': data['blocking_sha256'],
        'requested_edge_distributions': [{'vertices': list(k), **v} for k, v in data['edge_distributions'].items()],
        'edge_node_counts': [{'vertices': list(k), 'nodes': v} for k, v in data['edge_counts'].items()],
        'note': 'Fingerprint identity and pure-hexa checks do not prove CAD fit or full mesh conformity.'
    }, indent=2), encoding='utf-8')
    return replay


def compare_volume(check_text, cad_volume_mm3, relative_tolerance=0.01):
    """A necessary completeness check; does not replace boundary conformity checks."""
    if not math.isfinite(cad_volume_mm3) or cad_volume_mm3 <= 0:
        raise ValueError('Positive finite CAD volume required')
    if not 0 < relative_tolerance < 1:
        raise ValueError('Invalid relative volume tolerance')
    match = re.search(r'(?im)^\s*total volume:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)', check_text)
    if not match:
        raise ValueError('Fluent total mesh volume missing')
    measured = float(match.group(1))
    if not math.isfinite(measured) or measured <= 0:
        raise ValueError('Positive finite mesh volume required')
    error = abs(measured-cad_volume_mm3)/cad_volume_mm3
    return {'cad_volume_mm3': cad_volume_mm3, 'mesh_volume_mm3': measured,
            'relative_volume_error': error, 'volume_relative_tolerance': relative_tolerance,
            'volume_match_ok': error <= relative_tolerance}
