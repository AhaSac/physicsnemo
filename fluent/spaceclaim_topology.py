# Python Script, API Version = V242
"""Read-only CAD adjacency export for designing conformal ICEM blocking.

IDs are local to each export. They must not be reused as ICEM entity numbers.
Geometry remains authoritative; sampled curves are for classification only.
"""
import json
import os
import traceback


def xyz(point):
    return [point.X, point.Y, point.Z]


def extract(source):
    DocumentOpen.Execute(source)
    root = GetRootPart()
    bodies = list(root.GetAllBodies())
    if len(bodies) != 1:
        raise ValueError('Expected one fluid body')
    faces = list(bodies[0].Faces)
    face_ids = dict((f.GetHashCode(), i) for i, f in enumerate(faces))
    edge_shapes = {}
    edge_faces = {}
    for i, face in enumerate(faces):
        for edge in face.Edges:
            shape = edge.Master.Shape
            key = shape.GetHashCode()
            if key in edge_shapes and edge_shapes[key] != shape:
                raise ValueError('Edge identifier collision')
            edge_shapes[key] = shape
            edge_faces.setdefault(key, set()).add(i)
    edge_ids = dict((key, i) for i, key in enumerate(sorted(edge_shapes)))
    vertices = {}

    def vertex_id(vertex):
        if vertex is None:
            return None
        # SpaceClaim returns distinct wrappers for the same modeler vertex.
        # Preserve topology: coordinates alone must never merge disconnected points.
        incident = tuple(sorted(edge_ids[e.GetHashCode()] for e in vertex.Edges))
        position = xyz(vertex.Position)
        key = (incident, tuple(position))
        if key not in vertices:
            vertices[key] = {'id': len(vertices), 'position_m': position,
                             'incident_edges': list(incident), 'precision_m': vertex.Precision}
        return vertices[key]['id']

    edge_records = []
    for key, index in sorted(edge_ids.items(), key=lambda x: x[1]):
        edge = edge_shapes[key]
        bounds = edge.Bounds
        samples = [xyz(edge.Geometry.Evaluate(bounds.Start + (bounds.End - bounds.Start) * j / 16.0).Point)
                   for j in range(17)]
        edge_records.append({'id': index, 'curve_type': str(edge.Geometry.GetType().Name),
                             'length_m': edge.Length, 'start_vertex': vertex_id(edge.StartVertex),
                             'end_vertex': vertex_id(edge.EndVertex), 'faces': sorted(edge_faces[key]),
                             'fin_count': len(list(edge.Fins)), 'samples_m': samples})
    face_records = []
    for i, face in enumerate(faces):
        loops = []
        shape = face.Master.Shape
        for loop in shape.Loops:
            loops.append({'outer': bool(loop.IsOuter), 'fins': [
                {'edge': edge_ids[fin.Edge.GetHashCode()], 'reversed': bool(fin.IsReversed)} for fin in loop.Fins]})
        box = shape.GetBoundingBox(Matrix.Identity)
        face_records.append({'id': i, 'area_m2': face.Area, 'surface_type': str(shape.Geometry.GetType().Name),
                             'bbox_min_m': xyz(box.MinCorner), 'bbox_max_m': xyz(box.MaxCorner), 'loops': loops})
    groups = {}
    for group in root.Groups:
        groups[group.Name] = [face_ids[m.GetHashCode()] for m in group.Members if m.GetHashCode() in face_ids]
    return {'input': source, 'volume_m3': bodies[0].Master.Shape.Volume, 'coordinate_unit': 'm', 'coordinate_frame': 'body master', 'id_scope': 'this export only',
            'vertices': sorted(vertices.values(), key=lambda x: x['id']),
            'edges': edge_records, 'faces': face_records, 'face_groups': groups,
            'edge_fin_counts_ok': all(e['fin_count'] == 2 for e in edge_records)}


with open(os.environ['PUMP_TOPOLOGY_CONFIG']) as stream:
    jobs = json.load(stream)
for job in jobs:
    try:
        result = extract(job['input'])
    except:
        result = {'input': job['input'], 'error': traceback.format_exc()}
    with open(job['output'], 'w') as stream:
        json.dump(result, stream, indent=2)
