from __future__ import annotations
from engine.curve import PiecewiseFlatForwardCurve

# Credit curve Q(0,t): survival probability, built from piecewise-constant forward
# default (hazard) rates. Same mathematical form as the discount curve -- see
# curve.py -- just applied to hazard rate instead of interest rate.
#
# The Newton-Raphson bootstrap that calibrates this curve from CDS market spreads
# lives in bootstrap.py, not here: this module is just the curve object itself,
# kept separate so pricing.py can depend on "a curve with a survival_probability
# method" without needing to know how it was calibrated.


class HazardCurve(PiecewiseFlatForwardCurve):
    """Survival curve Q(0,t). Thin, differently-named wrapper over the shared
    piecewise-flat-forward machinery in curve.py -- see survival_probability().
    """

    def survival_probability(self, t: float) -> float:
        return self.value_at(t)
