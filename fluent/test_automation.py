import math
import json
from pathlib import Path
import tempfile
import unittest

from icem_structured import load_template, sha256, generate_hex_replay, compare_volume
from quality import assess
from run_meshing import load_config, boundary_mapping, load_trials
from icem_backend import generate_replay, tcl_path
from mesh_backend import face_quality, generated_boundary_ids
from types import SimpleNamespace


class QualityTests(unittest.TestCase):
    def check(self, skew=0.65, orth=0.2, **extra):
        return assess(skew, orth, cells=100, mesh_check_ok=True, named_boundaries_ok=True, **extra)['passed']

    def test_exact_default_volume_threshold_passes(self):
        self.assertTrue(self.check())

    def test_exact_surface_threshold_fails(self):
        self.assertFalse(self.check(skew=0.7))

    def test_strict_volume_threshold(self):
        self.assertFalse(self.check(orth=0.3, orthogonal_limit=0.3, orthogonal_strict=True))
        self.assertTrue(self.check(orth=0.30001, orthogonal_limit=0.3, orthogonal_strict=True))

    def test_missing_or_nonfinite_measurement(self):
        for value in (None, math.nan, math.inf, -0.1, 1.1, True):
            self.assertFalse(self.check(skew=value))
            self.assertFalse(self.check(orth=value))

    def test_orthogonal_only_policy(self):
        self.assertTrue(self.check(skew=0.95, orth=0.15, enforce_surface_limit=False, orthogonal_limit=0.15))
        self.assertFalse(self.check(skew=0.95, orth=0.149, enforce_surface_limit=False, orthogonal_limit=0.15))
        self.assertFalse(self.check(orth=math.nan, enforce_surface_limit=False))

    def test_topology_and_names_required(self):
        for key in ('mesh_check_ok', 'named_boundaries_ok'):
            kwargs = dict(cells=100, mesh_check_ok=True, named_boundaries_ok=True)
            kwargs[key] = False
            self.assertFalse(assess(0.5, 0.5, **kwargs)['passed'])


class ConfigurationTests(unittest.TestCase):
    def test_protobuf_zone_vectors_are_normalized(self):
        from ansys.api.fluent.v0.variant_pb2 import Variant
        ids = Variant()
        ids.int64_vector_state.item.extend([2, 3, 4])
        names = Variant()
        names.string_vector_state.item.extend(['origin-wall', 'wall', 'interior-fluid'])
        class Util:
            def get_face_zones(self, **kwargs):
                assert kwargs['only_boundary'] is True
                return ids.int64_vector_state.item
            def convert_zone_ids_to_name_strings(self, zone_id_list):
                assert type(zone_id_list) is list
                return names.string_vector_state.item
        self.assertEqual(generated_boundary_ids(SimpleNamespace(meshing_utilities=Util())), [3])

    def test_fixed_configs_differ_only_in_acceptance(self):
        root = Path(__file__).parent
        normal = json.loads((root / 'repeatable_config.json').read_text())
        complex_case = json.loads((root / 'complex_config.json').read_text())
        self.assertEqual(normal.pop('orthogonal_limit'), 0.2)
        self.assertEqual(complex_case.pop('orthogonal_limit'), 0.15)
        self.assertEqual(normal, complex_case)
        config = load_config('pump_repeatable', normal)
        self.assertEqual((config['min_size'], config['max_size'], config['volume_target']), (0.04, 8.0, 0.3))
        self.assertFalse(config['enforce_surface_limit'])
        self.assertTrue(config['workflow_defaults'])
        self.assertEqual(config['surface_improve_overrides'], {})

    def test_invalid_override_rejected(self):
        for changes in ({'min_size': -1}, {'min_size': 5}, {'max_size': math.inf}, {'min_size': math.nan}, {'cores': 0}, {'typo': 1}, {'boundary_layers': 1.5}):
            with self.assertRaises(ValueError):
                load_config('poly', changes)

    def test_sweep_rejects_duplicate_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sweep.json'
            for entries in ([{'name': '../escape', 'parameters': {}}],
                            [{'name': 'same', 'parameters': {}}] * 2,
                            [{'name': name, 'parameters': {}} for name in ('Fine', 'fine')]):
                path.write_text(json.dumps(entries))
                with self.assertRaises(ValueError):
                    load_trials(path)
            path.write_text(json.dumps([{'name': 'fine', 'parameters': {'max_size': 1.5}}]))
            self.assertEqual(load_config('poly', load_trials(path)[0]['parameters'])['max_size'], 1.5)

    def test_preset_selection_changes_real_backend(self):
        self.assertEqual(load_config('poly_hexcore')['volume_fill'], 'poly-hexcore')
        self.assertEqual(load_config('icem_tetra')['backend'], 'icem')
        self.assertEqual(load_config('tetra_prism')['boundary_layers'], 5)

    def test_known_geometry_name_typo_is_explicit(self):
        self.assertIn('2imperller_volute', boundary_mapping('2impeller'))

    def test_icem_paths_cannot_inject_tcl(self):
        with self.assertRaises(ValueError):
            tcl_path('bad}name.scdoc')

    def test_replay_is_parameterized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = generate_replay(Path(directory) / 'part.scdoc', Path(directory), load_config('icem_tetra_prism'))
            text = path.read_text()
            self.assertNotIn('@SOURCE@', text)
            self.assertIn('ic_run_prism', text)
            self.assertIn('nlay 5', text)
            self.assertIn('ICEM_LICENSE_UNAVAILABLE', text)



class StructuredTemplateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'pump.scdoc'
        self.source.write_bytes(b'geometry identity fixture')
        for name in ('geometry.tin', 'blocking.blk'):
            (self.root / name).write_bytes(name.encode())
        self.data = {'source_sha256': sha256(self.source), 'length_unit': 'mm', 'cad_volume_mm3': 10440.0,
                     'geometry': 'geometry.tin', 'blocking': 'blocking.blk',
                     'geometry_sha256': sha256(self.root / 'geometry.tin'),
                     'blocking_sha256': sha256(self.root / 'blocking.blk'),
                     'fluid_families': ['FLUID'], 'edge_groups': {'span': [[21, 22]]},
                     'node_counts': {'span': 5}}
        self.manifest = self.root / 'template.json'
        self.save()
        self.config = load_config('icem_hex', {'icem_hex_templates': {'pump': str(self.manifest)}})

    def save(self):
        self.manifest.write_text(json.dumps(self.data))

    def test_directed_edge_spacing_conflicts_and_reversal(self):
        from icem_structured import resolve_distributions
        groups = {'forward': [[21, 22]], 'reverse': [[22, 21]]}
        settings = {'forward': {'start_spacing_mm': 0.1, 'end_spacing_mm': 0.2},
                    'reverse': {'start_spacing_mm': 0.2, 'end_spacing_mm': 0.1}}
        self.assertEqual(resolve_distributions(groups, settings)[(21,22)], settings['forward'])
        settings['reverse']['start_spacing_mm'] = 0.3
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            resolve_distributions(groups, settings)
        for value in (True, -1, 0, math.nan, math.inf):
            with self.assertRaises(ValueError):
                resolve_distributions(groups, {'forward': {'start_spacing_mm': value}})
        with self.assertRaises(ValueError):
            resolve_distributions(groups, {'forward': {'start_growth': 0.9}})
        with self.assertRaises(ValueError):
            resolve_distributions(groups, {'forward': {'typo': 1}})

    def test_volume_completeness_requires_measured_total(self):
        self.assertTrue(compare_volume('  total volume: 1.044000e+04.', 10440)['volume_match_ok'])
        self.assertFalse(compare_volume('total volume: 5.000e+03', 10440)['volume_match_ok'])
        with self.assertRaises(ValueError):
            compare_volume('Done.', 10440)

    def test_wrong_geometry_and_changed_template_rejected(self):
        self.source.write_bytes(b'changed geometry')
        with self.assertRaisesRegex(ValueError, 'source geometry'):
            load_template(self.source, self.config)
        self.source.write_bytes(b'geometry identity fixture')
        (self.root / 'blocking.blk').write_bytes(b'changed blocking')
        with self.assertRaisesRegex(ValueError, 'blocking template'):
            load_template(self.source, self.config)

    def test_shared_edge_conflicting_counts_rejected(self):
        self.data['edge_groups']['other'] = [[22, 21]]
        self.data['node_counts']['other'] = 7
        self.save()
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            load_template(self.source, self.config)

    def test_unknown_direction_and_missing_template_rejected(self):
        self.config['icem_hex_node_counts'] = {'typo': 7}
        with self.assertRaisesRegex(ValueError, 'unknown overrides'):
            load_template(self.source, self.config)
        with self.assertRaisesRegex(ValueError, 'No verified'):
            load_template(self.source, {})

    def test_template_replay_uses_hexa_and_checks_requested_nodes(self):
        self.config['icem_hex_node_counts'] = {'span': 9}
        replay = generate_hex_replay(self.source, self.root / 'run', self.config).read_text()
        self.assertIn('ic_hex_set_mesh 21 22 n 9', replay)
        self.assertIn('ic_hex_get_edge_param 21 22 nodes] != 9', replay)
        self.assertIn('ic_hex_restore_blocking', replay)
        self.assertIn('Mesh is not pure HEXA_8', replay)
        self.assertNotIn('ic_run_tetra', replay)
        self.assertNotIn('@BLOCKING@', replay)

class MeshConnectivityTests(unittest.TestCase):
    def test_shared_face_connects_cells_but_two_boundary_faces_do_not(self):
        from mesh_connectivity import audit
        with tempfile.TemporaryDirectory() as directory:
            mesh = Path(directory) / 'mesh.msh'
            mesh.write_text('(12 (0 1 2 0 0))\n(13 (1 1 1 2 4)(1 2 3 4 1 2))')
            self.assertEqual(audit(mesh)['face_connected_components'], 1)
            mesh.write_text('(12 (0 1 2 0 0))\n(13 (1 1 2 3 4)(1 2 3 4 1 0 1 2 3 4 2 0))')
            self.assertEqual(audit(mesh)['face_connected_components'], 2)
            self.assertFalse(audit(mesh)['single_connected_volume'])

    def test_incomplete_cell_coverage_is_rejected(self):
        from mesh_connectivity import audit
        with tempfile.TemporaryDirectory() as directory:
            mesh = Path(directory) / 'mesh.msh'
            mesh.write_text('(12 (0 1 2 0 0))\n(13 (1 1 1 3 4)(1 2 3 4 1 0))')
            with self.assertRaisesRegex(ValueError, 'every cell'):
                audit(mesh)



class GeometryPreparationTests(unittest.TestCase):
    def test_silent_exit_cannot_reuse_previous_success(self):
        from unittest.mock import patch
        from run_meshing import prepare
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.scdoc'
            source.write_bytes(b'new source')
            output = root / 'prepared'
            output.mkdir()
            (output / '2impeller.scdoc').write_bytes(b'old geometry')
            (output / 'geometry.json').write_text(json.dumps({'coverage_ok': True, 'faces': 8, 'run_id': 'previous'}))
            with patch('run_meshing.subprocess.run'):
                with self.assertRaisesRegex(RuntimeError, 'fresh report'):
                    prepare('2impeller', source, output)
            self.assertFalse((output / 'cache.json').exists())

    def test_verified_export_is_cached_but_modified_export_is_not(self):
        import hashlib
        from unittest.mock import patch
        from run_meshing import prepare
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.scdoc'
            source.write_bytes(b'source')
            output = root / 'prepared'
            def export(*args, **kwargs):
                config = json.loads((output / 'spaceclaim_config.json').read_text())
                content = b'new exported geometry'
                Path(config['output']).write_bytes(content)
                Path(config['report']).write_text(json.dumps({'run_id': config['run_id'], 'coverage_ok': True,
                    'faces': 8, 'output_sha256': hashlib.sha256(content).hexdigest()}))
            with patch('run_meshing.subprocess.run', side_effect=export) as runner:
                geometry = prepare('2impeller', source, output)
                self.assertEqual(prepare('2impeller', source, output), geometry)
                self.assertEqual(runner.call_count, 1)
            geometry.write_bytes(b'changed outside the workflow')
            with patch('run_meshing.subprocess.run'):
                with self.assertRaisesRegex(RuntimeError, 'fresh report'):
                    prepare('2impeller', source, output)

if __name__ == '__main__':
    unittest.main()
