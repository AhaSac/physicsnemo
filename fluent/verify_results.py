"""Count independently evidenced passing model/backend combinations."""
import json
import hashlib
from pathlib import Path
from quality import assess


def verified_pairs(root):
    passed = set()
    for path in root.glob('**/quality.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        limits = data.get('thresholds', {})
        result = assess(data.get('surface_max_skewness'), data.get('volume_min_orthogonal'),
                        cells=data.get('cells'), mesh_check_ok=data.get('mesh_check_ok'),
                        named_boundaries_ok=data.get('named_boundaries_ok'), **limits)
        mesh = path.parent / data.get('mesh_file', 'mesh.msh.h5')
        if result['passed'] and mesh.is_file() and mesh.stat().st_size > 0 and data.get('mesh_sha256') == hashlib.sha256(mesh.read_bytes()).hexdigest():
            passed.add((data['model'], data['backend']))
    return passed


if __name__ == '__main__':
    print(len(verified_pairs(Path(__file__).parent / 'outputs')))
