"""验证工程数据约定；不以伪造性能数据证明模型的工程预测精度。"""

import csv
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

import train_openfoam_pump as pump


class DataContractTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "sample_id": "p1", "geometry_id": "g1", "n_rpm": 3000.0,
            "Q_m3_s": 0.01, "rho_kg_m3": 1000.0, "mu_Pa_s": 0.001,
            "H_m": 20.0, "T_Nm": 10.0, "converged": "true",
        }

    def test_nondimensionalisation_and_physical_round_trip(self):
        cond, hs, ts = pump.condition_and_scales(self.row, 0.2)
        # 3000 rpm = 50转/秒；这项检查可以发现把rpm直接代入相似系数的错误。
        self.assertAlmostEqual(math.exp(cond[0]), 50)
        self.assertAlmostEqual(hs, 50**2 * 0.2**2)
        self.assertAlmostEqual(math.exp(cond[5]), 0.01 / (50 * 0.2**3))
        g = 9.80665
        pred = np.array([[math.log(g * 20 / hs), math.log(10 / ts)]])
        stats = {"target_mean": np.zeros(2), "target_std": np.ones(2)}
        result = pump.decode_predictions(pred, [self.row], {"g1": (None, 0.2)}, stats, g)[0]
        self.assertAlmostEqual(result["H_pred_m"], 20)
        self.assertAlmostEqual(result["T_pred_Nm"], 10)
        self.assertAlmostEqual(result["eta_pred"], 1000 * g * 0.01 * 20 / (10 * 100 * math.pi))

    def test_zero_flow_and_negative_rpm_rejected(self):
        for key, value in (("Q_m3_s", 0), ("n_rpm", -3000), ("mu_Pa_s", float("nan"))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                pump.condition_and_scales({**self.row, key: value}, 0.2)

    def test_geometry_group_leakage_rejected(self):
        rows = [{"geometry_id": "g1", "split": "train"}, {"geometry_id": "g1", "split": "val"}]
        with self.assertRaises(ValueError):
            pump.assign_splits(rows, 42)

    def test_automatic_group_split_is_reproducible(self):
        rows = [{"geometry_id": f"g{i}", "split": ""} for i in range(12) for _ in range(3)]
        other = [dict(r) for r in rows]
        pump.assign_splits(rows, 42)
        pump.assign_splits(other, 42)
        self.assertEqual(rows, other)
        self.assertEqual({r["split"] for r in rows}, {"train", "val", "test"})
        for gid in {r["geometry_id"] for r in rows}:
            self.assertEqual(len({r["split"] for r in rows if r["geometry_id"] == gid}), 1)

    def test_mixed_explicit_and_automatic_splits_rejected(self):
        with self.assertRaises(ValueError):
            pump.assign_splits([{"geometry_id": "g1", "split": "train"}, {"geometry_id": "g2", "split": ""}], 42)

    def test_canonical_frame_preserves_distances_and_units(self):
        spec = {"rotation_origin": [100, 0, 0], "rotation_axis": [0, 1, 0], "radial_reference": [1, 0, 0]}
        origin, basis = pump.canonical_basis(spec, 0.001)
        np.testing.assert_allclose(origin, [0.1, 0, 0])
        np.testing.assert_allclose(basis.T @ basis, np.eye(3))
        self.assertAlmostEqual(np.linalg.det(basis), 1)
        np.testing.assert_allclose(np.array([0, 1, 0]) @ basis, [0, 0, 1])

    def test_parallel_radial_reference_rejected(self):
        spec = {"rotation_origin": [0, 0, 0], "rotation_axis": [0, 0, 1], "radial_reference": [0, 0, 2]}
        with self.assertRaises(ValueError):
            pump.canonical_basis(spec, 1)

    def test_all_four_parts_are_sampled_reproducibly(self):
        pool = np.zeros((4, 32, 8), dtype=np.float32)
        for i in range(4):
            pool[i, :, 0] = np.arange(32)
            pool[i, :, 3 + i] = 1
        sampled = pump.sample_points(pool, 64, 42)
        np.testing.assert_array_equal(sampled, pump.sample_points(pool, 64, 42))
        np.testing.assert_array_equal(sampled[:, 3:7].sum(0), [16, 16, 16, 16])
        self.assertFalse(np.array_equal(sampled, pump.sample_points(pool, 64, 43)))

    def test_label_csv_rejects_unconverged_and_impossible_efficiency(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "samples.csv"
            for changes in ({"converged": "false"}, {"T_Nm": 0.001}):
                row = {**self.row, **changes}
                with path.open("w", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(file, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerow(row)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    pump.load_rows(path, {"g1": 0.2}, 9.80665)

    def test_training_stats_do_not_mutate_or_read_holdout_rows(self):
        self.row["target_log_coeff"] = [0.3, -2.0]
        stats = pump.make_stats([self.row], {"g1": (None, 0.2)})
        np.testing.assert_allclose(stats["target_mean"], [0.3, -2.0])
        self.assertTrue(np.all(stats["condition_std"] >= 0.05))
        self.assertTrue(np.all(stats["target_std"] >= 0.05))


if __name__ == "__main__":
    unittest.main()
