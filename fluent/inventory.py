"""Read SCDOC metadata without changing the original CAD documents."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


def inspect_scdoc(path):
    path = Path(path).resolve()
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError('Corrupt archive member: ' + bad)
        root = ET.fromstring(archive.read('SpaceClaim/document.xml'))
        ns = {'s': 'urn:stored selection'}
        groups = []
        for node in root.findall('.//s:NamedSelectionDef', ns):
            groups.append({'name': node.findtext('s:name', namespaces=ns),
                           'members': len(node.findall('s:objects/s:item/s:item', ns))})
        return {'path': str(path), 'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'archive_ok': True, 'geometry_validated': False,
                'groups': groups}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = []
    for path in sorted(args.directory.glob('*.scdoc')):
        item = inspect_scdoc(path)
        item['excluded'] = path.stem.lower() in ('1impeller', 'impeller1')
        records.append(item)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'models': len(records), 'eligible': sum(not r['excluded'] for r in records)}))
