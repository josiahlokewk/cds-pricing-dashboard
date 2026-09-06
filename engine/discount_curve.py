from __future__ import annotations
from typing import List, Sequence
from engine.curve import PiecewiseFlatForwardCurve

# OIS/SOFR discount curve bootstrap.
#
# Unlike the credit curve (hazard rates from CDS spreads), this bootstrap is linear:
# given a par OIS swap rate for a new, longest maturity, and every shorter discount
# factor already solved, the new discount factor appears exactly once, to the first
# power, in the swap's par condition -- so it is solved directly, with no
# Newton-Raphson / no iteration.
#
# Simplifying assumption, stated explicitly: each OIS swap's fixed leg is treated as
# paying at the curve's own node maturities (e.g. 0.5, 1, 2, 3, ..., 30y), using the
# gap between consecutive quoted nodes as the accrual period, rather than assuming a
# separate annual payment schedule with dates that don't align to the quoted curve.
# This mirrors how the CDS assignment itself documents its own day-count/schedule
# simplifications rather than leaving them implicit.


class OISCurve(PiecewiseFlatForwardCurve):
    """Discount curve Z(0,t). Thin, differently-named wrapper over the shared
    piecewise-flat-forward machinery in curve.py -- see discount_factor().
    """

    def discount_factor(self, t: float) -> float:
        return self.value_at(t)


def bootstrap_ois_curve(node_years: Sequence[float], par_rates: Sequence[float]) -> OISCurve:
    """Bootstrap discount factors from market-quoted par OIS swap rates.

    node_years: sorted maturities in years, e.g. [0.5, 1, 2, 3, 4, 5, 7, 10, 20, 30]
    par_rates: matching par OIS rates as decimals (e.g. 0.045 for 4.5%)

    Par condition for a swap of maturity T_n, with all shorter discount factors
    already known: C(T_n) * sum_i(delta_i * Z(0,t_i)) = 1 - Z(0,T_n), where the sum
    runs over all node payment dates up to and including T_n. Rearranged for the one
    unknown, Z(0,T_n):

        Z(0,T_n) = (1 - C(T_n) * annuity_so_far) / (1 + C(T_n) * delta_n)

    where annuity_so_far = sum_i(delta_i * Z(0,t_i)) over strictly earlier nodes.
    """
    if len(node_years) != len(par_rates):
        raise ValueError("node_years and par_rates must be the same length")

    discount_factors: List[float] = []
    annuity_so_far = 0.0
    t_prev = 0.0

    for t, C in zip(node_years, par_rates):
        delta = t - t_prev
        Z = (1.0 - C * annuity_so_far) / (1.0 + C * delta)
        discount_factors.append(Z)
        annuity_so_far += delta * Z
        t_prev = t

    return OISCurve(node_years, discount_factors)
