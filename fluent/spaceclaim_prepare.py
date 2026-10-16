# Python Script, API Version = V242
"""Run inside SpaceClaim 2024 R2; paths/configuration supplied through PUMP_CONFIG.

Preserves original CAD. Groups existing topological faces, validates complete
non-overlapping coverage, and exports geometry fingerprints for reproducibility.
"""
import json
import hashlib
import os
import traceback


def point_values(point):
    return [point.X, point.Y, point.Z]


def face_record(face):
    box = face.Shape.GetBoundingBox(Matrix.Identity)
    return {'area_m2': face.Area, 'bbox_min_m': point_values(box.MinCorner),
            'bbox_max_m': point_values(box.MaxCorner),
            'surface_type': str(face.Shape.Geometry.GetType().Name)}


def same_face(actual, reference, linear_tolerance, area_tolerance):
    if actual['surface_type'] != reference['surface_type']:
        return False
    if abs(actual['area_m2'] - reference['area_m2']) > max(abs(reference['area_m2']) * area_tolerance, 1e-14):
        return False
    for key in ('bbox_min_m', 'bbox_max_m'):
        if any(abs(a - b) > linear_tolerance for a, b in zip(actual[key], reference[key])):
            return False
    return True


def rebuild_groups(root, body, config):
    """Rebuild groups from geometry, never from unstable face index numbers."""
    with open(config['template']) as stream:
        template = json.load(stream)
    faces = list(body.Faces)
    signatures = [face_record(face) for face in faces]
    used = set()
    selections = {}
    for source, target in config['groups'].items():
        if target.startswith('fluid_'):
            selections[source] = [body]
            continue
        selected = []
        for reference in template['groups'][target]:
            matches = [index for index, sig in enumerate(signatures) if index not in used and
                       same_face(sig, reference, config.get('linear_tolerance_m', 1e-7),
                                 config.get('relative_area_tolerance', 1e-5))]
            if len(matches) != 1:
                raise ValueError('Ambiguous or missing geometry match for ' + target + ': ' + str(len(matches)))
            index = matches[0]
            used.add(index)
            selected.append(faces[index])
        selections[source] = selected
    if len(used) != len(faces):
        raise ValueError('Template does not cover all faces of this geometry')
    # Validate the entire correspondence before changing any named selection.
    for name, members in selections.items():
        existing = dict((group.Name, group) for group in root.Groups)
        if name in existing:
            NamedSelection.Replace(name, Selection.Create(members), Selection.Empty())
        else:
            before = set(existing.keys())
            NamedSelection.Create(Selection.Create(members), Selection.Empty())
            created = [group.Name for group in root.Groups if group.Name not in before]
            if len(created) != 1:
                raise ValueError('Expected exactly one newly created named selection')
            NamedSelection.Rename(created[0], name)


def run(config):
    DocumentOpen.Execute(config['input'])
    root = GetRootPart()
    bodies = list(root.GetAllBodies())
    if len(bodies) != 1:
        raise ValueError('Expected one already extracted fluid body, got %d' % len(bodies))
    body = bodies[0]
    if config.get('template'):
        rebuild_groups(root, body, config)
    faces = list(body.Faces)
    groups = dict((group.Name, group) for group in root.Groups)
    mapping = config['groups']
    records = {}
    covered = set()
    for source, target in mapping.items():
        if source not in groups:
            raise ValueError('Required named selection missing: ' + source)
        group = groups[source]
        members = list(group.Members)
        if not members:
            raise ValueError('Empty named selection: ' + source)
        if target.startswith('fluid_'):
            if len(members) != 1 or 'DesignBody' not in str(members[0].GetType()):
                raise ValueError('Fluid selection must contain one body')
            RenameObject.Execute(Selection.Create(body), target)
        else:
            entries = []
            for face in members:
                if 'DesignFace' not in str(face.GetType()):
                    raise ValueError('Non-face member in boundary ' + source)
                key = face.GetHashCode()
                if key in covered:
                    raise ValueError('Overlapping boundary selections: ' + source)
                covered.add(key)
                entries.append(face_record(face))
            records[target] = entries
        if source != target:
            NamedSelection.Rename(source, target)
    if len(covered) != len(faces):
        raise ValueError('Boundary coverage mismatch: %d of %d faces' % (len(covered), len(faces)))
    box = body.Shape.GetBoundingBox(Matrix.Identity)
    report = {'input': config['input'], 'faces': len(faces), 'coverage_ok': True,
              'bbox_min_m': point_values(box.MinCorner), 'bbox_max_m': point_values(box.MaxCorner),
              'groups': records, 'mapping': mapping}
    DocumentSave.Execute(config['output'])
    report['run_id'] = config.get('run_id')
    with open(config['output'], 'rb') as exported:
        report['output_sha256'] = hashlib.sha256(exported.read()).hexdigest()
    with open(config['report'], 'w') as stream:
        json.dump(report, stream, indent=2)


with open(os.environ['PUMP_CONFIG']) as stream:
    configuration = json.load(stream)
try:
    run(configuration)
except:
    with open(configuration['report'], 'w') as stream:
        json.dump({'error': traceback.format_exc(), 'run_id': configuration.get('run_id')}, stream, indent=2)
    raise
