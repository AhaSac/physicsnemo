"""Reapply the saved native workflow volume improvement, without remeshing CAD."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from mesh_backend import launch, write_json, cell_quality, face_quality, generated_boundary_ids, checked_mesh
from quality import assess
from inventory import inspect_scdoc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('--target', type=float, default=0.3)
    args = parser.parse_args()
    if not 0 < args.target < 1:
        parser.error('target must be between zero and one')
    case = args.case.resolve()
    job = json.loads((case / 'job.json').read_text(encoding='utf-8'))
    old = json.loads((case / 'quality.json').read_text(encoding='utf-8'))
    config = dict(job['config'], volume_target=args.target)
    out = case.parent.parent.parent / (time.strftime('%Y%m%d_%H%M%S') + '_' + str(os.getpid())) / job['model'] / 'native_volume_refine'
    out.mkdir(parents=True)
    job.update(config=config, output=str(out), preset='native_volume_refine', parent_case=str(case))
    write_json(out / 'job.json', job)
    write_json(out / 'parameters.json', config)
    result = {'model': job['model'], 'backend': 'fluent', 'status': 'running', 'passed': False,
              'mesh_unit': 'mm', 'parent_case': str(case)}
    started = time.monotonic()
    print('OUTPUT', out, flush=True)
    session = launch(out, config)
    try:
        session.transcript.start(file_name=str(out / 'fluent.trn'), write_to_stdout=True)
        session.tui.file.read_mesh((case / old['mesh_file']).as_posix())
        before = cell_quality(session)
        task = session.workflow.TaskObject['Improve Volume Mesh']
        task.Arguments.set_state({'CellQualityLimit': args.target})
        write_json(out / 'native_volume_improve_arguments.json', task.Arguments.get_state())
        task.Execute()
        after = cell_quality(session)
        skew, zones = face_quality(session, generated_boundary_ids(session))
        expected = [g['name'].lower() for g in inspect_scdoc(Path(job['source']))['groups'] if not g['name'].startswith('fluid_')]
        named_ok = all(any(prefix + name in zones for prefix in ('', 'zone')) for name in expected)
        checked = checked_mesh(session, out)
        mesh = out / 'mesh.msh.h5'
        session.tui.file.write_mesh(mesh.as_posix())
        limits = {k: config[k] for k in ('surface_limit', 'orthogonal_limit', 'orthogonal_strict')}
        result.update(assess(skew, after['min'], cells=after['count'], mesh_check_ok=checked, named_boundaries_ok=named_ok, **limits))
        result.update(status='passed' if result['passed'] else 'quality_not_met',
                      mesh_file=mesh.name, mesh_sha256=hashlib.sha256(mesh.read_bytes()).hexdigest(),
                      thresholds=limits, volume_history=[before, after], final_boundary_zones=zones,
                      named_boundaries_ok=named_ok, mesh_check_ok=checked)
    except Exception as error:
        result.update(status='error', error=str(error))
        raise
    finally:
        result['elapsed_seconds'] = time.monotonic() - started
        write_json(out / 'quality.json', result)
        session.exit(timeout=10, wait=5)
    print(json.dumps({k: result[k] for k in ('status', 'surface_max_skewness', 'volume_min_orthogonal', 'cells')}))
    return 0 if result['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
