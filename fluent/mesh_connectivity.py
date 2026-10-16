"""Audit face adjacency in ASCII Fluent meshes (independent of zone labels)."""
import argparse
import collections
import json
import re
from pathlib import Path


def audit(path):
    text = Path(path).read_text(encoding='ascii')
    header = re.search(r'\(12\s+\(0\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+0(?:\s+0)?\)\)', text)
    if not header:
        raise ValueError('ASCII Fluent global cell header required')
    first, last = (int(x,16) for x in header.groups())
    if first != 1 or last < first:
        raise ValueError('Expected nonempty contiguous cell IDs starting at 1')
    parents = list(range(last+1))
    seen = set()
    def root(n):
        while parents[n] != n:
            parents[n] = parents[parents[n]]
            n = parents[n]
        return n
    faces = internal = boundary = 0
    for section in re.finditer(r'\(13\s+\(([^)]*)\)\s*\((.*?)\)\s*\)', text, re.S):
        h = [int(v,16) for v in section[1].split()]
        if len(h) != 5 or h[2] < h[1] or h[4] not in (0,3,4):
            raise ValueError('Unsupported face section')
        values = iter(section[2].split())
        for _ in range(h[2]-h[1]+1):
            try:
                count = h[4] or int(next(values),16)
                if count < 3:
                    raise ValueError('Invalid face node count')
                nodes = [int(next(values),16) for _ in range(count)]
                a,b = int(next(values),16),int(next(values),16)
            except StopIteration as exc:
                raise ValueError('Truncated face section') from exc
            if min(nodes) < 1 or not 0 <= a <= last or not 0 <= b <= last or a == b:
                raise ValueError('Invalid face adjacency')
            seen.update(c for c in (a,b) if c)
            faces += 1
            if a and b:
                parents[root(a)] = root(b)
                internal += 1
            else:
                boundary += 1
        if next(values, None) is not None:
            raise ValueError('Extra face section data')
    if len(seen) != last:
        raise ValueError('Face sections do not cover every cell')
    sizes = collections.Counter(root(n) for n in seen)
    return {'cells': last, 'face_connected_components': len(sizes),
            'component_cell_counts': sorted(sizes.values()), 'faces': faces,
            'internal_faces': internal, 'boundary_faces': boundary,
            'single_connected_volume': len(sizes) == 1,
            'scope': 'Face connectivity only; also require geometric and mesh-quality audits.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mesh')
    parser.add_argument('--output')
    args = parser.parse_args()
    result = audit(args.mesh)
    encoded = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(encoded, encoding='utf-8')
    print(encoded)
