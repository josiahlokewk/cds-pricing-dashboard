from __future__ import annotations
import math
from typing import List, Sequence

# Shared machinery for both the discount curve (Z(t), built from rates) and the
# credit curve (Q(t), built from hazard rates). 
# Both are piecewise-constant-forward decay functions of the same mathematical form:
#   Z(t) = exp(-integral of r(s) ds from 0 to t)      -- discounting
#   Q(t) = exp(-integral of h(s) ds from 0 to t)       -- survival probability
#
# with r(s) / h(s) held flat between calibration nodes.


class PiecewiseFlatForwardCurve:
    """A curve of the form value(t) = exp(-integral of piecewise-flat forward rate),
    exact at the calibrated node maturities, flat-forward interpolated in between,
    and flat-extrapolated beyond the last node.
    """

    def __init__(self, node_years: Sequence[float], node_values: Sequence[float]):
        if list(node_years) != sorted(node_years):
            raise ValueError("node_years must be sorted ascending")
        
        if len(node_years) != len(node_values):
            raise ValueError("node_years and node_values must be the same length")
        
        self.node_years: List[float] = list(node_years)
        self.node_values: List[float] = list(node_values) # survival probabilities

    def value_at(self, t: float) -> float:
        """
        Linear interpolation of f(t) = -ln Q(t) for survival curves.
        Linear interpolation of f(t) = -ln Z(t) for discount curves.
        """

        if t <= 0:
            return 1.0

        nodes = self.node_years
        values = self.node_values # survival probabilities / discount factors

        t_prev, v_prev = 0.0, 1.0
        for t_next, v_next in zip(nodes, values):
            if t <= t_next:
                forward = -math.log(v_next / v_prev) / (t_next - t_prev) # slope formula (y1 - y2) / (x1-x2)
                return v_prev * math.exp(-forward * (t - t_prev))
            t_prev, v_prev = t_next, v_next

        # Beyond the last node: flat-extrapolate using the final segment's forward rate.
        t_last_prev = nodes[-2] if len(nodes) > 1 else 0.0
        v_last_prev = values[-2] if len(values) > 1 else 1.0
        forward = -math.log(values[-1] / v_last_prev) / (nodes[-1] - t_last_prev)
        return values[-1] * math.exp(-forward * (t - nodes[-1]))

    def forward_rate(self, t1: float, t2: float) -> float:
        """The flat forward rate implied by the curve between t1 and t2. Callers
        should only invoke this over an interval that doesn't straddle a calibration
        node other than possibly at its endpoints -- see critical_dates() in
        pricing.py, which is what guarantees that for the protection-leg integral.
        """

        v1 = self.value_at(t1)
        v2 = self.value_at(t2)
        return -math.log(v2 / v1) / (t2 - t1)
