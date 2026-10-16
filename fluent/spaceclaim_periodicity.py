# Python Script, API Version = V242
"""Read-only sampled CAD symmetry diagnostic; does not certify periodic geometry."""
import os
import json
import math
import traceback


def coords(p):
    return [p.X, p.Y, p.Z]


def run(job):
    DocumentOpen.Execute(job['input'])
    root = GetRootPart()
    group = next(g for g in root.Groups if g.Name == job['wall_group'])
    faces = [m.Master.Shape for m in group.Members]
    boxes = [f.GetBoundingBox(Matrix.Identity) for f in faces]
    edges = {}
    for face in faces:
        for edge in face.Edges:
            edges[edge.GetHashCode()] = edge
    samples = []
    for edge in edges.values():
        bounds = edge.Bounds
        for frac in (0.0, 0.5, 1.0):
            samples.append(coords(edge.Geometry.Evaluate(bounds.Start + frac * (bounds.End - bounds.Start)).Point))
    results = []
    for angle in (0.0, job['angle_degrees'], -job['angle_degrees']):
        theta = angle * math.pi / 180.0
        cosine, sine = math.cos(theta), math.sin(theta)
        distances = []
        worst = None
        for x, y, z in samples:
            q = [cosine*x-sine*y, sine*x+cosine*y, z]
            point = Point.Create(*q)
            candidates = []
            for i, box in enumerate(boxes):
                low, high = coords(box.MinCorner), coords(box.MaxCorner)
                bound = sum(max(low[k]-q[k], q[k]-high[k], 0.0)**2 for k in range(3))
                candidates.append((bound, i))
            best = float('inf')
            for bound, i in sorted(candidates):
                if bound > best:
                    break
                p = coords(faces[i].ProjectPoint(point).Point)
                best = min(best, sum((p[k]-q[k])**2 for k in range(3)))
            value = math.sqrt(best)*1000.0
            distances.append(value)
            if worst is None or value > worst['distance_mm']:
                worst = {'distance_mm': value, 'rotated_point_m': q}
        distances.sort()
        results.append({'angle_degrees': angle, 'samples': len(distances),
                        'max_distance_mm': distances[-1], 'median_distance_mm': distances[len(distances)//2],
                        'p95_distance_mm': distances[int(0.95*(len(distances)-1))],
                        'worst': worst})
    return {'input': job['input'], 'wall_group': job['wall_group'], 'assumed_rotation_axis': 'body-master Z through (0,0)',
            'method': 'Rotate edge endpoints/midpoints; project to exact trimmed wall faces',
            'scope': 'Sampled necessary condition only; not a proof of full CAD periodicity', 'results': results}

with open(os.environ['PUMP_PERIODICITY_CONFIG']) as stream:
    jobs = json.load(stream)
for job in jobs:
    try:
        result = run(job)
    except:
        result = {'input': job['input'], 'error': traceback.format_exc()}
    with open(job['output'], 'w') as stream:
        json.dump(result, stream, indent=2)
