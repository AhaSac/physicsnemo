"""Validate exported CAD adjacency and classify disconnected named wall patches."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def connected_components(nodes, adjacency):
    remaining = set(nodes)
    result = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        component, pending = {seed}, [seed]
        while pending:
            for node in adjacency[pending.pop()] & remaining:
                remaining.remove(node)
                component.add(node)
                pending.append(node)
        result.append(sorted(component))
    return result


def analyze(path):
    path = Path(path)
    raw = path.read_bytes()
    data = json.loads(raw)
    if 'error' in data:
        raise ValueError(data['error'])
    vertices = {v['id']: v for v in data['vertices']}
    edges = {e['id']: e for e in data['edges']}
    faces = {f['id']: f for f in data['faces']}
    errors = []
    edge_uses = Counter()
    face_adjacency = {i: set() for i in faces}
    for edge in edges.values():
        if edge['fin_count'] != 2:
            errors.append('Edge %d is not two-sided' % edge['id'])
        for v in (edge['start_vertex'], edge['end_vertex']):
            if v is not None and edge['id'] not in vertices[v]['incident_edges']:
                errors.append('Edge/vertex incidence mismatch %d' % edge['id'])
        for i in edge['faces']:
            face_adjacency[i].update(set(edge['faces']) - {i})
    for face in faces.values():
        for loop in face['loops']:
            chain = []
            for fin in loop['fins']:
                edge = edges[fin['edge']]
                edge_uses[edge['id']] += 1
                pair = (edge['start_vertex'], edge['end_vertex'])
                chain.append(pair[::-1] if fin['reversed'] else pair)
            if not chain or any(a[1] != b[0] for a, b in zip(chain, chain[1:] + chain[:1])):
                errors.append('Open directed loop on face %d' % face['id'])
    if any(edge_uses[i] != 2 for i in edges):
        errors.append('Face-loop coverage is not exactly two fins per edge')
    roles = {}
    for name, ids in data['face_groups'].items():
        if name.startswith('fluid_'):
            continue
        for i in ids:
            if i in roles:
                errors.append('Overlapping named face membership %d' % i)
            roles[i] = name
    if set(roles) != set(faces):
        errors.append('Named faces do not cover the boundary')
    patches = []
    for name, ids in data['face_groups'].items():
        if not name.endswith('_wall'):
            continue
        for index, component in enumerate(connected_components(ids, face_adjacency)):
            members = set(component)
            boundaries = {}
            for edge in edges.values():
                inside = set(edge['faces']) & members
                outside = set(edge['faces']) - members
                if not inside or not outside:
                    continue
                for i in outside:
                    boundaries.setdefault(roles[i], []).append(edge['id'])
            patches.append({'wall_group': name, 'component': index, 'face_ids': component,
                            'area_mm2': sum(faces[i]['area_m2'] for i in component)*1e6,
                            'bbox_min_mm': [min(faces[i]['bbox_min_m'][j] for i in component)*1000 for j in range(3)],
                            'bbox_max_mm': [max(faces[i]['bbox_max_m'][j] for i in component)*1000 for j in range(3)],
                            'neighbor_groups_and_edges': boundaries})
    return {'source': data['input'], 'topology_sha256': hashlib.sha256(raw).hexdigest(),
            'id_scope': 'IDs refer only to the hashed CAD topology export, never directly to ICEM',
            'coordinate_frame': data['coordinate_frame'], 'topology_checks_passed': not errors,
            'errors': errors, 'vertices': len(vertices), 'edges': len(edges), 'faces': len(faces),
            'boundary_shell_components': len(connected_components(faces, face_adjacency)),
            'euler_characteristic': len(vertices)-len(edges)+sum(2-len(f['loops']) for f in faces.values()),
            'wall_patch_components': patches,
            'limitation': 'Wall components are geometric candidates; this is not a blocking or mesh conformity certificate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('topology', nargs='+', type=Path)
    args = parser.parse_args()
    failed = False
    for path in args.topology:
        result = analyze(path)
        target = path.with_suffix('.features.json')
        target.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(path.stem, 'checks=', result['topology_checks_passed'], 'wall_components=', len(result['wall_patch_components']))
        failed |= not result['topology_checks_passed']
    if failed:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
