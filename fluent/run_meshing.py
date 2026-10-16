"""Python entry point for the ANSYS 2024 R2 pump meshing automation."""
import argparse
import csv
import hashlib
import math
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

HERE = Path(__file__).resolve().parent
ANSYS = Path(r'C:\Program Files\ANSYS Inc\v242')
INPUTS = Path(r'C:\Users\AhaSac\Desktop\pump\0907wang\xt\imperfectimpeller')


def boundary_mapping(model):
    n = model[0]
    prefix = n + 'impeller'
    if n == '2':
        return {prefix + '_interface': 'interface_in_' + prefix,
                '2imperller_volute': 'interface_out_' + prefix,
                'fluid_' + prefix: 'fluid_' + prefix,
                prefix + '_upwall': 'wall_upper_' + prefix,
                prefix + '_downwall': 'wall_lower_' + prefix,
                prefix + '_wall': 'wall_blades_' + prefix}
    return {prefix + '_int': 'interface_in_' + prefix,
            prefix + '_out': 'interface_out_' + prefix,
            'fluid_' + prefix: 'fluid_' + prefix,
            prefix + '_upface': 'wall_upper_' + prefix,
            prefix + '_downface': 'wall_lower_' + prefix,
            prefix + '_wall': 'wall_blades_' + prefix}


def prepare(model, source, output, reference=None):
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(source.read_bytes() + (HERE / 'spaceclaim_prepare.py').read_bytes() + (reference.read_bytes() if reference else b'')).hexdigest()
    cached = output / 'cache.json'
    geometry = output / (model + '.scdoc')
    if cached.exists() and geometry.is_file():
        cache_data = json.loads(cached.read_text())
        if (cache_data.get('fingerprint') == fingerprint and
                cache_data.get('output_sha256') == hashlib.sha256(geometry.read_bytes()).hexdigest()):
            return geometry
    config = {'input': str(source.resolve()), 'output': str(geometry),
              'report': str(output / 'geometry.json'), 'groups': boundary_mapping(model),
              'run_id': uuid.uuid4().hex}
    if reference:
        config['template'] = str(reference.resolve())
    path = output / 'spaceclaim_config.json'
    path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    env = dict(os.environ, PUMP_CONFIG=str(path), AWP_ROOT242=str(ANSYS), AWP_ROOT=str(ANSYS))
    command = [str(ANSYS / 'scdm/SpaceClaim.exe'), '/Headless=True', '/Splash=False',
               '/Welcome=False', '/ScriptAPI=242', '/ExitAfterScript=True',
               '/RunScript=' + str(HERE / 'spaceclaim_prepare.py'),
               '/ScriptOutput=' + str(output / 'spaceclaim.log')]
    with (output / 'process.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, cwd=output, env=env, check=True, timeout=300,
                       stdout=log, stderr=subprocess.STDOUT,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    report_path = Path(config['report'])
    if not report_path.is_file():
        raise RuntimeError('SpaceClaim did not produce a report for this invocation')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('run_id') != config['run_id']:
        raise RuntimeError('SpaceClaim did not produce a fresh report; previous output cannot certify this invocation')
    if report.get('error') or not report.get('coverage_ok'):
        raise RuntimeError(report)
    if not geometry.is_file() or not geometry.stat().st_size:
        raise RuntimeError('SpaceClaim did not export a nonempty geometry file')
    output_hash = hashlib.sha256(geometry.read_bytes()).hexdigest()
    if report.get('output_sha256') != output_hash:
        raise RuntimeError('SpaceClaim exported geometry does not match its report')
    cached.write_text(json.dumps({'fingerprint': fingerprint, 'output_sha256': output_hash}), encoding='utf-8')
    print(json.dumps({'model': model, 'geometry': report['faces'], 'coverage_ok': True}), flush=True)
    return Path(config['output'])


def load_config(preset, overrides=None):
    catalog = json.loads((HERE / 'presets.json').read_text(encoding='utf-8'))
    if preset not in catalog['presets']:
        raise ValueError('Unknown preset: ' + preset)
    config = dict(catalog['defaults'], **catalog['presets'][preset])
    overrides = overrides or {}
    unknown = set(overrides) - set(config) - {'surface_controls'}
    if unknown:
        raise ValueError('Unknown parameters: ' + ', '.join(sorted(unknown)))
    config.update(overrides)
    for key in ('min_size', 'max_size', 'growth_rate', 'curvature_angle', 'first_height', 'layer_growth',
                'surface_improve_min_size', 'timeout_seconds'):
        if not isinstance(config[key], (int, float)) or isinstance(config[key], bool) or not math.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(key + ' must be positive')
    for key in ('cores', 'surface_improve_iterations', 'volume_improve_iterations', 'improve_passes'):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(key + ' must be a positive integer')
    if type(config['cells_per_gap']) is not int or config['cells_per_gap'] < 1:
        raise ValueError('cells_per_gap must be a positive integer')
    if type(config['boundary_layers']) is not int or config['boundary_layers'] < 0:
        raise ValueError('boundary_layers must be a nonnegative integer')
    if (
        not isinstance(config.get('wall_exclude_names'), list)
        or any(not isinstance(name, str) or not name.strip() for name in config['wall_exclude_names'])
    ):
        raise ValueError('wall_exclude_names must be a list of nonempty strings')
    if type(config['improve_layered_mesh']) is not bool:
        raise ValueError('improve_layered_mesh must be boolean')
    if type(config['enforce_surface_limit']) is not bool:
        raise ValueError('enforce_surface_limit must be boolean')
    if config['min_size'] > config['max_size']:
        raise ValueError('min_size cannot exceed max_size')
    if not 0 < config['surface_target'] < config['surface_limit'] <= 1:
        raise ValueError('Require 0 < surface_target < surface_limit <= 1')
    if not 0 <= config['orthogonal_limit'] <= config['volume_target'] < 1:
        raise ValueError('Invalid orthogonal quality target')
    if config['length_unit'] != 'mm':
        raise ValueError('This pump workflow uses millimetres for sizing and exported mesh coordinates')
    if config['backend'] not in ('fluent', 'icem'):
        raise ValueError('Unsupported backend')
    if config['backend'] == 'icem' and config.get('icem_method') not in ('tetra', 'hexa'):
        raise ValueError('Unsupported ICEM meshing method')
    if config['backend'] == 'icem' and (config['local_sizing'] or config.get('surface_controls') or any(config[k] for k in ('surface_overrides', 'volume_overrides', 'boundary_layer_overrides', 'surface_improve_overrides'))):
        raise ValueError('Fluent-specific sizing/overrides cannot be used with ICEM')
    return config


def execute_worker(job):
    from mesh_backend import fluent_mesh
    from icem_backend import icem_mesh
    function = fluent_mesh if job['config']['backend'] == 'fluent' else icem_mesh
    return function(Path(job['source']), Path(job['output']), job['config'])


def load_trials(path):
    if path is None:
        return [{'name': '', 'parameters': {}}]
    trials = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(trials, list) or not trials:
        raise ValueError('Sweep must be a nonempty list of named parameter objects')
    names = set()
    for trial in trials:
        if not isinstance(trial, dict) or set(trial) != {'name', 'parameters'}:
            raise ValueError('Each sweep entry requires name and parameters')
        name = trial['name']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', name) or name.casefold() in names:
            raise ValueError('Sweep names must be unique and contain only letters, digits, _ or -')
        if not isinstance(trial['parameters'], dict):
            raise ValueError('Sweep parameters must be an object')
        names.add(name.casefold())
    return trials


def summarize(root):
    rows = []
    for path in root.glob('**/quality.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        job_path = path.parent / 'job.json'
        job = json.loads(job_path.read_text(encoding='utf-8')) if job_path.exists() else {}
        rows.append({key: data.get(key) for key in ('model', 'backend', 'status', 'passed', 'surface_max_skewness',
                    'volume_min_orthogonal', 'cells', 'elapsed_seconds')} | {
                        'preset': job.get('preset', path.parent.name), 'trial': job.get('trial', ''), 'report': str(path)})
    (root / 'summary.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    best = {}
    for row in rows:
        if row['passed'] is True and row['status'] == 'passed':
            rank = (row['volume_min_orthogonal'], -row['surface_max_skewness'], -row['cells'])
            previous = best.get(row['model'])
            if previous is None or rank > (previous['volume_min_orthogonal'], -previous['surface_max_skewness'], -previous['cells']):
                best[row['model']] = row
    (root / 'best_measured.json').write_text(json.dumps({
        'selection_rule': 'Passed reports only; highest minimum orthogonal quality, then lowest maximum boundary skewness, then fewest cells. Only compares the measured cases, not a global optimum.',
        'models': best}, ensure_ascii=False, indent=2), encoding='utf-8')
    if rows:
        with (root / 'summary.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'mesh', 'batch', 'plan', 'replay', 'audit', 'presets', 'summary', '_worker'])
    parser.add_argument('--case-dir', type=Path)
    parser.add_argument('--mesh-file', help='For audit only: an existing mesh filename inside --case-dir')
    parser.add_argument('--models', nargs='+', choices=['2impeller', '3impeller', '4impeller'], default=['2impeller', '3impeller', '4impeller'])
    parser.add_argument('--input-dir', type=Path, default=INPUTS)
    parser.add_argument('--schemes', nargs='+', default=['pump_repeatable'])
    parser.add_argument('--cores', type=int)
    parser.add_argument('--config', type=Path, help='JSON parameter overrides applied to selected presets')
    parser.add_argument('--sweep', type=Path, help='JSON list of {name, parameters} trials applied after --config')
    parser.add_argument('--job', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--skip-prepare', action='store_true', help='Use original named SCDOC files')
    parser.add_argument('--reference', type=Path, help='geometry.json template to reconstruct missing groups (one model only)')
    parser.add_argument('--output', type=Path, default=HERE / 'outputs' / 'runs')
    args = parser.parse_args()
    if args.action == 'audit':
        if args.case_dir is None:
            parser.error('audit requires --case-dir')
        from mesh_backend import audit_case
        result = audit_case(args.case_dir, args.mesh_file)
        summarize(args.case_dir.parent.parent)
        print(json.dumps({key: result[key] for key in ('status', 'surface_max_skewness', 'volume_min_orthogonal', 'cells')}))
        if not result['passed']:
            raise SystemExit(2)
        return
    if args.action == '_worker':
        execute_worker(json.loads(args.job.read_text(encoding='utf-8')))
        return
    if args.action == 'presets':
        print((HERE / 'presets.json').read_text(encoding='utf-8'))
        return
    if args.action == 'summary':
        print(json.dumps(summarize(args.output), ensure_ascii=False, indent=2))
        return
    overrides = json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
    if args.cores is not None:
        overrides['cores'] = args.cores
    trials = load_trials(args.sweep)
    configs = [(name, trial['name'], load_config(name, overrides | trial['parameters']))
               for name in dict.fromkeys(args.schemes) for trial in trials]
    run_id = time.strftime('%Y%m%d_%H%M%S') + '_' + str(os.getpid())
    run_root = args.output.resolve() / run_id
    jobs = []
    for model in dict.fromkeys(args.models):
        source = args.input_dir / (model + '.scdoc')
        if not source.is_file():
            raise FileNotFoundError(source)
        for scheme, trial, config in configs:
            folder = scheme + ('__' + trial if trial else '')
            jobs.append({'model': model, 'preset': scheme, 'trial': trial, 'source': str(source.resolve()),
                         'output': str(run_root / model / folder), 'config': config})
    if args.action == 'plan':
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        return
    if args.action == 'prepare':
        if args.reference and len(args.models) != 1:
            raise ValueError('A geometry reference applies to one selected model')
        for model in args.models:
            prepare(model, args.input_dir / (model + '.scdoc'), HERE / 'outputs' / model / ('restored' if args.reference else 'geometry'), args.reference)
        return
    if args.action == 'replay':
        from icem_backend import generate_replay
        for job in jobs:
            if job['config']['backend'] != 'icem':
                raise ValueError('replay requires an ICEM preset')
            path = generate_replay(Path(job['source']), Path(job['output']), job['config'])
            print(path)
        return
    run_root.mkdir(parents=True, exist_ok=True)
    for job in jobs:
        output = Path(job['output'])
        output.mkdir(parents=True, exist_ok=True)
        print('START', job['model'], job['preset'], str(output), flush=True)
        try:
            if not args.skip_prepare:
                job['source'] = str(prepare(job['model'], Path(job['source']), HERE / 'outputs' / job['model'] / 'geometry'))
            job_path = output / 'job.json'
            job_path.write_text(json.dumps(job, indent=2), encoding='utf-8')
            with (output / 'worker.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve()), '_worker', '--job', str(job_path)],
                                           stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    code = process.wait(timeout=job['config']['timeout_seconds'])
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                    raise TimeoutError('Job exceeded configured timeout; its process tree was stopped')
            if code:
                raise RuntimeError('Worker exited %s; see worker.log' % code)
            print('FINISHED', job['model'], job['preset'], flush=True)
            measured = json.loads((output / 'quality.json').read_text(encoding='utf-8'))
            print(json.dumps({key: measured.get(key) for key in ('status', 'surface_max_skewness', 'volume_min_orthogonal', 'cells')}), flush=True)
        except Exception:
            error = traceback.format_exc()
            print('FAILED', job['model'], job['preset'], error.splitlines()[-1], flush=True)
            report = output / 'quality.json'
            if not report.exists():
                report.write_text(json.dumps({'model': job['model'], 'backend': job['config']['backend'],
                                             'status': 'error', 'passed': False, 'error': error}, indent=2), encoding='utf-8')
        summarize(run_root)
    final_rows = summarize(run_root)
    print('REPORT', str(run_root / 'summary.csv'), flush=True)
    if any(row['status'] in ('error', 'license_blocked') for row in final_rows):
        raise SystemExit(1)
    if any(not row['passed'] for row in final_rows):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
