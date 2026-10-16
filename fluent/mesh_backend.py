"""Version-pinned Fluent Meshing workflow with measured quality and evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import time
import traceback

from inventory import inspect_scdoc
from quality import assess


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def _normalized_boundary_name(name):
    value = name.lower().strip()
    for prefix in ('zone', 'fam'):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value


def _is_wall_boundary_name(name):
    value = _normalized_boundary_name(name)
    return not (
        value.startswith('fluid_')
        or 'interface' in value
        or value.endswith(('_int', '_in', '_out', 'inlet', 'outlet'))
    )


def _excluded_boundary_names(config):
    return {_normalized_boundary_name(name) for name in config.get('wall_exclude_names', [])}


def _is_excluded_boundary(name, excluded):
    value = _normalized_boundary_name(name)
    return any(value == item or value.endswith(item) for item in excluded)


def launch(output, config):
    import ansys.fluent.core as pyfluent
    # PyFluent's env argument is used as the child process environment. Start
    # with the complete Windows environment; passing only license variables
    # can remove PATH/SystemRoot and prevent cx2410.exe from initializing.
    env = dict(os.environ)
    env['AWP_ROOT'] = config['ansys_root']
    env['AWP_ROOT242'] = config['ansys_root']
    return pyfluent.launch_fluent(
        fluent_path=str(Path(config['ansys_root']) / 'fluent/ntbin/win64/fluent.exe'),
        product_version='24.2.0', mode='meshing', precision='double',
        processor_count=config['cores'], ui_mode='no_gui', start_timeout=120,
        cwd=str(output), start_watchdog=True,
        env=env)


def face_quality(session, zone_ids):
    """Use name-pattern queries: 242 silently rejects the ID-list form here."""
    util = session.meshing_utilities
    names = list(util.convert_zone_ids_to_name_strings(zone_id_list=list(zone_ids)) or [])
    if not names:
        raise RuntimeError('No generated mesh face zones found')
    values = {}
    for name in names:
        raw = util.get_face_quality_limits(face_zone_name_pattern=name, measure='Skewness')
        if not isinstance(raw, (tuple, list)) or len(raw) != 5:
            raise RuntimeError('Unrecognized Fluent 242 face quality response: %r' % raw)
        values[name] = {'worst_face': raw[0], 'min': raw[1], 'max': raw[2], 'mean': raw[3], 'count': raw[4]}
    return max(v['max'] for v in values.values()), values


def cell_quality(session):
    raw = session.meshing_utilities.get_cell_quality_limits(cell_zone_name_pattern='*', measure='Orthogonal Quality')
    if not isinstance(raw, (tuple, list)) or len(raw) != 6 or raw[0] <= 0:
        raise RuntimeError('Unrecognized Fluent 242 volume quality response: %r' % raw)
    return {'count': int(raw[0]), 'min': raw[1], 'max': raw[2], 'mean': raw[3], 'raw': raw}


def generated_boundary_ids(session):
    util = session.meshing_utilities
    ids = list(util.get_face_zones(maximum_entity_count=1e15, only_boundary=True) or [])
    names = list(util.convert_zone_ids_to_name_strings(zone_id_list=ids) or [])
    if not ids or len(names) != len(ids):
        raise RuntimeError('Cannot map Fluent boundary IDs to names: ids=%r (%s), names=%r (%s)' % (ids, type(ids).__name__, names, type(names).__name__))
    return [zone for zone, name in zip(ids, names)
            if not name.startswith(('origin-', 'interior'))]


def checked_mesh(session, output):
    chunks = []
    callback = session.transcript.register_callback(chunks.append, keep_new_lines=True)
    try:
        session.tui.mesh.check_mesh()
        # Flush a complete final line through the transcript stream.
        session.scheme_eval.exec(('(newline)', '(display "PUMP_MESH_CHECK_END")', '(newline)'))
        deadline = time.monotonic() + 10
        while not any('PUMP_MESH_CHECK_END' in chunk for chunk in chunks) and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        session.transcript.unregister_callback(callback)
    text = ''.join(chunks)
    (output / 'mesh_check.txt').write_text(text, encoding='utf-8')
    errors = re.search(r'(?im)^\s*(?:error\b|warning\b)|negative\s+volume|non-positive\s+volume|invalid\s+mesh', text)
    return bool('Done.' in text and 'PUMP_MESH_CHECK_END' in text and not errors)


def improve_volume(session, config, output):
    before = cell_quality(session)
    history = [before]
    if config['boundary_layers'] and not config.get('improve_layered_mesh', False):
        # 242 ImproveVolumeMesh stalled on both tested layered impeller meshes.
        # Export measured mesh and let the parameter sweep try the next design.
        return history
    best = before['min']
    checkpoint = output / 'best_volume.msh.h5'
    session.tui.file.write_mesh(checkpoint.as_posix())
    for index in range(config['improve_passes']):
        if best >= config['volume_target']:
            break
        session.meshing.ImproveVolumeMesh(
            CellQualityLimit=config['volume_target'], QualityMethod='Orthogonal',
            VMImprovePreferences={'VIQualityIterations': config['volume_improve_iterations']})
        after = cell_quality(session)
        history.append(after)
        if after['min'] + 1e-12 < best:
            session.tui.file.read_mesh(checkpoint.as_posix())
            break
        if after['min'] > best:
            best = after['min']
            # Unique paths avoid interactive overwrite prompts.
            checkpoint = output / ('best_volume_%d.msh.h5' % index)
            session.tui.file.write_mesh(checkpoint.as_posix())
        else:
            break
    return history


def audit_case(output, mesh_file=None):
    """Re-open the actual exported mesh and remeasure, without regenerating it."""
    output = Path(output).resolve()
    result = json.loads((output / 'quality.json').read_text(encoding='utf-8'))
    config = json.loads((output / 'parameters.json').read_text(encoding='utf-8'))
    if mesh_file is not None:
        if Path(mesh_file).name != mesh_file or not (output / mesh_file).is_file():
            raise ValueError('Audit mesh override must name an existing file inside the case directory')
        result['mesh_file'] = mesh_file
        result['audit_mesh_override'] = mesh_file
        if 'error' in result:
            result['generation_error'] = result.pop('error')
    result.setdefault('thresholds', {key: config[key] for key in
                      ('surface_limit', 'orthogonal_limit', 'orthogonal_strict')})
    result['thresholds'].setdefault('enforce_surface_limit', config.get('enforce_surface_limit', True))
    result.setdefault('mesh_unit', config['length_unit'])
    mesh = output / result['mesh_file']
    session = launch(output, config)
    started = time.monotonic()
    try:
        session.transcript.start(file_name=str(output / 'audit.trn'), write_to_stdout=True)
        session.tui.file.read_mesh(mesh.as_posix())
        skew, zones = face_quality(session, generated_boundary_ids(session))
        cells = cell_quality(session)
        ok = checked_mesh(session, output)
        source = Path(json.loads((output / 'job.json').read_text(encoding='utf-8'))['source'])
        expected = [g['name'].lower() for g in inspect_scdoc(source)['groups'] if not g['name'].startswith('fluid_')]
        actual = [name.lower() for name in zones]
        named_ok = all(any(prefix + name in actual for prefix in ('', 'zone', 'fam')) for name in expected)
        result['previous_audit_status'] = result['status']
        result.update(assess(skew, cells['min'], cells=cells['count'], mesh_check_ok=ok,
                            named_boundaries_ok=named_ok, **result.get('thresholds', {})))
        result.update({'mesh_check_ok': ok, 'named_boundaries_ok': named_ok, 'final_boundary_zones': zones,
                       'status': 'passed' if result['passed'] else 'quality_not_met',
                       'audit_seconds': round(time.monotonic() - started, 3),
                       'mesh_sha256': hashlib.sha256(mesh.read_bytes()).hexdigest()})
        write_json(output / 'quality.json', result)
        return result
    finally:
        session.exit(timeout=10, wait=5)


def fluent_mesh(source, output, config):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    write_json(output / 'parameters.json', config)
    expected = [g['name'] for g in inspect_scdoc(source)['groups'] if not g['name'].startswith('fluid_')]
    session = launch(output, config)
    result = {'model': source.stem, 'backend': 'fluent', 'version': str(session.get_fluent_version()),
              'passed': False, 'status': 'running', 'mesh_unit': config['length_unit']}
    try:
        session.transcript.start(file_name=str(output / 'fluent.trn'), write_to_stdout=True)
        workflow = session.workflow
        workflow.InitializeWorkflow(WorkflowType='Watertight Geometry')
        tasks = workflow.TaskObject
        native = config.get('workflow_defaults', False)
        controls = {'MinSize': config['min_size'], 'MaxSize': config['max_size']}
        controls['CellsPerGap'] = config['cells_per_gap']
        if not native:
            controls.update({'GrowthRate': config['growth_rate'], 'CurvatureNormalAngle': config['curvature_angle']})
        controls.update(config.get('surface_controls', {}))
        surface_args = {'CFDSurfaceMeshControls': controls}
        surface_args.update(config['surface_overrides'])
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        cache_key = {'source_sha256': source_hash, 'surface_args': surface_args,
                     'local_sizing': config['local_sizing'], 'length_unit': config['length_unit'],
                     'surface_improvement': {k: config.get(k) for k in ('workflow_defaults', 'surface_improve_overrides', 'surface_target', 'surface_improve_min_size', 'surface_improve_iterations', 'improve_passes')}}
        if config.get('surface_cache'):
            cache = Path(config['surface_cache']).resolve()
            info = json.loads(Path(str(cache) + '.json').read_text(encoding='utf-8'))
            if info['key'] != cache_key or info['mesh_sha256'] != hashlib.sha256(cache.read_bytes()).hexdigest():
                raise ValueError('Surface cache input/parameters/checksum do not match this job')
            session.tui.file.read_mesh(cache.as_posix())
        else:
            tasks['Import Geometry'].Arguments.set_state({'FileName': str(source), 'LengthUnit': config['length_unit']})
            tasks['Import Geometry'].Execute()
            for local in config['local_sizing']:
                tasks['Add Local Sizing'].Arguments.set_state(local)
                tasks['Add Local Sizing'].AddChildAndUpdate(DeferUpdate=False)
            tasks['Generate the Surface Mesh'].Arguments.set_state(surface_args)
            if native:
                write_json(output / 'native_surface_arguments.json', tasks['Generate the Surface Mesh'].Arguments.get_state())
            tasks['Generate the Surface Mesh'].Execute()
        util = session.meshing_utilities
        objects = util.get_objects(type_name='mesh')
        if len(objects) != 1:
            raise RuntimeError('Expected one fluid mesh object, got %r' % objects)
        def surface_measure():
            zones = generated_boundary_ids(session)
            return face_quality(session, zones)
        skew, zones = surface_measure()
        surface_history = [{'max_skewness': skew, 'zones': zones}]
        if native:
            tasks['Generate the Surface Mesh'].InsertNextTask(CommandName='ImproveSurfaceMesh')
            tasks['Improve Surface Mesh'].Arguments.set_state(config.get('surface_improve_overrides', {}))
            write_json(output / 'native_surface_improve_arguments.json', tasks['Improve Surface Mesh'].Arguments.get_state())
            tasks['Improve Surface Mesh'].Execute()
            skew, zones = surface_measure()
            surface_history.append({'max_skewness': skew, 'zones': zones})
        for attempt in range(0 if native else config['improve_passes']):
            if skew < config['surface_target']:
                break
            session.meshing.ImproveSurfaceMesh(
                MeshObject=objects[0], FaceQualityLimit=config['surface_target'],
                SQMinSize=config['surface_improve_min_size'],
                SMImprovePreferences={'SIQualityIterations': config['surface_improve_iterations'], 'AllowDefeaturing': 'no'})
            newer, zones = surface_measure()
            surface_history.append({'max_skewness': newer, 'zones': zones})
            if newer >= skew:
                skew = newer
                break
            skew = newer
        write_json(output / 'surface_quality.json', {'history': surface_history, 'max_skewness': skew})
        session.tui.file.write_mesh((output / 'surface.msh.h5').as_posix())
        write_json(output / 'surface.msh.h5.json', {'key': cache_key,
                   'mesh_sha256': hashlib.sha256((output / 'surface.msh.h5').read_bytes()).hexdigest()})
        tasks['Describe Geometry'].UpdateChildTasks(SetupTypeChanged=False)
        tasks['Describe Geometry'].Arguments.set_state({'SetupType': 'The geometry consists of only fluid regions with no voids'})
        tasks['Describe Geometry'].UpdateChildTasks(SetupTypeChanged=True)
        tasks['Describe Geometry'].Execute()
        if config.get('boundary_types'):
            tasks['Update Boundaries'].Arguments.set_state({
                'BoundaryLabelList': list(config['boundary_types']),
                'BoundaryLabelTypeList': list(config['boundary_types'].values())})
        else:
            excluded = _excluded_boundary_names(config)
            wall_types = {
                name: 'wall'
                for name in expected
                if _is_wall_boundary_name(name)
                and not _is_excluded_boundary(name, excluded)
            }
            if wall_types:
                tasks['Update Boundaries'].Arguments.set_state({
                    'BoundaryLabelList': list(wall_types),
                    'BoundaryLabelTypeList': list(wall_types.values())})
        tasks['Update Boundaries'].Execute()
        tasks['Update Regions'].Execute()
        if native:
            bl = {}
        elif config['boundary_layers']:
            zone_names = list(util.convert_zone_ids_to_name_strings(zone_id_list=generated_boundary_ids(session)))
            expected_names = [
                group['name'].lower()
                for group in inspect_scdoc(source)['groups']
                if not group['name'].lower().startswith('fluid_')
            ]

            excluded = _excluded_boundary_names(config)
            wall_expected = {
                _normalized_boundary_name(name)
                for name in expected_names
                if _is_wall_boundary_name(name)
                and not _is_excluded_boundary(name, excluded)
            }
            wall_names = [
                name for name in zone_names
                if _normalized_boundary_name(name) in wall_expected
            ]
            # The utility also returns the body label (fluid_*), which is not a
            # valid boundary-layer face label. The 242 workflow accepts these
            # generated boundary names as its explicit Labels choices.
            wall_labels = wall_names
            if not wall_labels:
                raise RuntimeError('Cannot find labelled wall faces for boundary layers')
            bl = {'AddChild': 'yes', 'BLControlName': 'wall_layers', 'OffsetMethodType': 'uniform',
                  'NumberOfLayers': config['boundary_layers'], 'FirstHeight': config['first_height'],
                  'Rate': config['layer_growth'], 'FaceScope': {'GrowOn': 'selected-labels'}, 'BlLabelList': wall_labels}
            bl.update(config['boundary_layer_overrides'])
        else:
            bl = {'AddChild': 'no'}
        write_json(output / 'boundary_layer_arguments.json', bl)
        if bl:
            tasks['Add Boundary Layers'].Arguments.set_state(bl)
        if native:
            write_json(output / 'native_boundary_layer_arguments.json', tasks['Add Boundary Layers'].Arguments.get_state())
        tasks['Add Boundary Layers'].AddChildAndUpdate(DeferUpdate=False)
        volume = {'VolumeFill': config['volume_fill']}
        volume.update(config['volume_overrides'])
        tasks['Generate the Volume Mesh'].Arguments.set_state(volume)
        if native:
            write_json(output / 'native_volume_arguments.json', tasks['Generate the Volume Mesh'].Arguments.get_state())
        tasks['Generate the Volume Mesh'].Execute()
        if native:
            history = [cell_quality(session)]
            session.tui.file.write_mesh((output / 'before_native_improve.msh.h5').as_posix())
            tasks['Generate the Volume Mesh'].InsertNextTask(CommandName='ImproveVolumeMesh')
            tasks['Improve Volume Mesh'].Arguments.set_state({'CellQualityLimit': config['volume_target']})
            write_json(output / 'native_volume_improve_arguments.json', tasks['Improve Volume Mesh'].Arguments.get_state())
            tasks['Improve Volume Mesh'].Execute()
            history.append(cell_quality(session))
        else:
            history = improve_volume(session, config, output)
        measured = cell_quality(session)
        all_zones = list(util.get_face_zones(filter='*'))
        names = list(util.convert_zone_ids_to_name_strings(zone_id_list=all_zones))
        boundary_names = [name for name in names if not name.startswith('interior')]
        missing = [name for name in expected if name not in boundary_names and 'zone' + name not in boundary_names]
        # Evaluate final boundary faces as well: polyhedral conversion can alter face shapes.
        boundary_ids = [zone for zone, name in zip(all_zones, names) if name in boundary_names]
        final_skew, final_zones = face_quality(session, boundary_ids)
        check_ok = checked_mesh(session, output)
        mesh = output / 'mesh.msh.h5'
        session.tui.file.write_mesh(mesh.as_posix())
        legacy_mesh = output / 'mesh.msh'
        legacy_mesh_error = None
        try:
            # The extension requests Fluent's legacy mesh format, which can
            # be read by older Fluent releases such as 2022 R1.
            session.tui.file.write_mesh(legacy_mesh.as_posix())
        except Exception as error:
            legacy_mesh_error = str(error)
        result.update(assess(final_skew, measured['min'], cells=measured['count'], mesh_check_ok=check_ok,
                             named_boundaries_ok=not missing, surface_limit=config['surface_limit'], enforce_surface_limit=config.get('enforce_surface_limit', True),
                             orthogonal_limit=config['orthogonal_limit'], orthogonal_strict=config['orthogonal_strict']))
        result.update({'surface_generation_max_skewness': skew, 'final_boundary_zones': final_zones,
                       'volume_improvement_skipped': bool(config['boundary_layers'] and not config.get('improve_layered_mesh', False)),
                       'volume_history': history, 'mesh_check_ok': check_ok, 'named_boundaries_ok': not missing,
                       'missing_boundaries': missing, 'boundary_names': boundary_names,
                       'mesh_file': mesh.name, 'legacy_mesh_file': legacy_mesh.name if legacy_mesh.is_file() else None,
                       'legacy_mesh_error': legacy_mesh_error,
                       'mesh_sha256': hashlib.sha256(mesh.read_bytes()).hexdigest(),
                       'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                       'status': 'passed' if result['passed'] else 'quality_not_met',
                       'thresholds': {'enforce_surface_limit': config.get('enforce_surface_limit', True), 'surface_limit': config['surface_limit'], 'orthogonal_limit': config['orthogonal_limit'],
                                      'orthogonal_strict': config['orthogonal_strict']}})
        return result
    except Exception:
        result.update({'status': 'error', 'error': traceback.format_exc()})
        raise
    finally:
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        write_json(output / 'quality.json', result)
        session.exit(timeout=10, wait=5)
