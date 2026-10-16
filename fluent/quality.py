"""Strict mesh acceptance: absent/NaN quality is always a failure."""
import math


def assess(surface_max_skewness, volume_min_orthogonal, *, cells, mesh_check_ok,
           named_boundaries_ok, surface_limit=0.7, orthogonal_limit=0.2,
           orthogonal_strict=False, enforce_surface_limit=True):
    def valid(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1
    reasons = []
    if enforce_surface_limit and (not valid(surface_max_skewness) or surface_max_skewness >= surface_limit):
        reasons.append('surface_max_skewness must be finite and < %s' % surface_limit)
    if not valid(volume_min_orthogonal) or volume_min_orthogonal < orthogonal_limit or (orthogonal_strict and volume_min_orthogonal == orthogonal_limit):
        reasons.append('volume_min_orthogonal does not meet %s%s' % ('>' if orthogonal_strict else '>=', orthogonal_limit))
    if not isinstance(cells, int) or isinstance(cells, bool) or cells <= 0:
        reasons.append('positive volume cell count required')
    if mesh_check_ok is not True:
        reasons.append('Fluent mesh check did not pass')
    if named_boundaries_ok is not True:
        reasons.append('named boundary preservation did not pass')
    return {'passed': not reasons, 'failures': reasons,
            'surface_max_skewness': surface_max_skewness,
            'volume_min_orthogonal': volume_min_orthogonal, 'cells': cells}
