"""Glue between the Flask routes and the engine/scripts layer: CSV parsing,
request -> price_standard_contract() dispatch, and converting the resulting
dict (which contains date objects, HazardCurve/OISCurve instances, etc.) into
plain JSON-serializable structures.

No pricing math lives here -- this module only shuffles data in and out of the
already-built, already-tested engine/scripts.* functions.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from scripts import standard_contract

# CSV formats this dashboard understands. Real Bloomberg exports may not match
# these exactly (their format isn't confirmed yet -- see project discussion) --
# these are a reasonable, documented starting point, adjustable once a real
# exported file is available to test against.
OIS_CSV_COLUMNS = ["years", "rate"]
CDS_CSV_COLUMNS = ["tenor", "years", "spread_bp"]

N_FINE_GRID_POINTS = 300


def default_ois_curve():
    return [{"years": y, "rate": r}
            for y, r in zip(standard_contract.OIS_NODE_YEARS, standard_contract.OIS_RATES)]


def default_cds_curve():
    return [{"tenor": tenor, "years": years, "spread_bp": spread_bp}
            for tenor, years, spread_bp in standard_contract.TABLE_1]


def default_contract_params():
    return {
        "standard": {
            "trade_date": standard_contract.TRADE_DATE.isoformat(),
            "tenor_years": standard_contract.OWN_TENOR_YEARS,
            "coupon_bp": standard_contract.OWN_COUPON * 10000.0,
            "recovery": standard_contract.OWN_RECOVERY,
            "notional": standard_contract.NOTIONAL,
            "calibration_recovery": standard_contract.CALIBRATION_RECOVERY,
        },
    }


class CsvParseError(ValueError):
    pass


def _read_csv_rows(file_storage):
    text = file_storage.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise CsvParseError("File appears to be empty.")
    return [{k.strip().lower(): v.strip() for k, v in row.items() if k} for row in reader], \
        [f.strip().lower() for f in reader.fieldnames]


def _read_xlsx_sheets(file_storage):
    """Yields (sheet_name, rows, fieldnames) for every sheet in the workbook that
    has a non-empty header row -- values as strings (matching _read_csv_rows'
    shape), so both formats can share one classifier below. .xlsx only (modern
    Excel XML format, via openpyxl) -- legacy binary .xls needs a different
    library (xlrd) and isn't handled here; see parse_uploaded_file's error for
    that case.
    """
    import openpyxl
    wb = openpyxl.load_workbook(file_storage, read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            continue
        if header is None or all(h is None for h in header):
            continue
        fieldnames = [str(h).strip().lower() for h in header if h is not None]
        rows = []
        for raw_row in rows_iter:
            if raw_row is None or all(v is None for v in raw_row):
                continue
            row = {}
            for name, value in zip(fieldnames, raw_row):
                row[name] = "" if value is None else str(value).strip()
            rows.append(row)
        yield ws.title, rows, fieldnames


def _classify_rows(rows, fieldnames):
    """Sniffs a header row to decide whether it's an OIS curve or a CDS spread
    curve, and parses accordingly. Raises CsvParseError (message only, used for
    both CSV and Excel) if it matches neither shape.
    """
    fieldset = set(fieldnames)

    if fieldset >= set(OIS_CSV_COLUMNS) and "spread_bp" not in fieldset:
        parsed = [{"years": float(row["years"]), "rate": float(row["rate"])} for row in rows]
        return {"kind": "ois", "rows": parsed}

    if fieldset >= set(CDS_CSV_COLUMNS):
        parsed = [{"tenor": row["tenor"], "years": float(row["years"]), "spread_bp": float(row["spread_bp"])}
                  for row in rows]
        return {"kind": "cds", "rows": parsed}

    raise CsvParseError(
        f"Unrecognized columns {fieldnames!r}. Expected either {OIS_CSV_COLUMNS} "
        f"(OIS curve) or {CDS_CSV_COLUMNS} (CDS spread curve)."
    )


def parse_uploaded_file(file_storage):
    """Dispatches on file extension. CSV: one sheet, one result. .xlsx: scans
    every sheet and classifies each independently, since a real Bloomberg
    workbook export may put the OIS curve and the CDS spread curve on separate
    tabs of the same file -- returns one result per sheet that actually matches
    a recognized shape (sheets that match neither, e.g. a notes/cover tab, are
    silently skipped rather than erroring the whole upload, since a workbook
    can have unrelated sheets that aren't meant to be data).
    """
    filename = (file_storage.filename or "").lower()

    if filename.endswith(".csv"):
        rows, fieldnames = _read_csv_rows(file_storage)
        return [_classify_rows(rows, fieldnames)]

    if filename.endswith(".xlsx"):
        results = []
        errors = []
        for sheet_name, rows, fieldnames in _read_xlsx_sheets(file_storage):
            try:
                results.append(_classify_rows(rows, fieldnames))
            except CsvParseError as e:
                errors.append(f"'{sheet_name}': {e}")
        if not results:
            raise CsvParseError("No sheet matched a recognized shape. " + " | ".join(errors))
        return results

    if filename.endswith(".xls"):
        raise CsvParseError(
            "Legacy .xls (pre-2007 Excel binary format) isn't supported yet -- "
            "only .csv and .xlsx. Please re-save as .xlsx or .csv."
        )

    raise CsvParseError(f"Unrecognized file type for '{file_storage.filename}'. Expected .csv or .xlsx.")


def _hazard_node_payload(tenors, spreads_bp, hazard_curve, discount_curve, histories):
    nodes = []
    t_prev = 0.0
    for tenor, spread_bp, t, history in zip(tenors, spreads_bp, hazard_curve.node_years, histories):
        h_final = history[-1][1]
        # Segment-level quantities (t_prev -> t), for showing the actual
        # substituted O'Kane-Turnbull arithmetic, not just the final converged
        # h/Q/Z at the end of the segment -- exact whenever this segment isn't
        # itself broken up by an intervening OIS node (true whenever the CDS
        # and OIS curves share the same node years, as in every default/
        # placeholder dataset in this project; flagged in the frontend if not).
        nodes.append({
            "tenor": tenor,
            "spread_bp": spread_bp,  # the market quote this node was calibrated against
            "t": t,
            "t_prev": t_prev,
            "h": h_final,
            "r": discount_curve.forward_rate(t_prev, t),
            "Q": hazard_curve.survival_probability(t),
            "Q_prev": hazard_curve.survival_probability(t_prev),
            "discount_factor": discount_curve.discount_factor(t),
            "discount_factor_prev": discount_curve.discount_factor(t_prev),
            "iterations": [{"iter": it, "x": x, "residual": fx, "derivative": dfx}
                            for it, x, fx, dfx in history],
        })
        t_prev = t
    return nodes


def _curve_fig_data(hazard_curve, discount_curve, ois_rates):
    max_t = max(hazard_curve.node_years[-1], discount_curve.node_years[-1])
    t_grid = [max_t * i / (N_FINE_GRID_POINTS - 1) for i in range(N_FINE_GRID_POINTS)]
    survival = [hazard_curve.survival_probability(t) for t in t_grid]
    discount = [discount_curve.discount_factor(t) for t in t_grid]
    return {
        "t": t_grid, "survival": survival, "discount": discount,
        # The OIS curve's own calibration nodes -- these are directly-input par
        # rates (no root-finding, unlike the hazard curve), so there's nothing
        # to animate, but they're still real input points worth marking on the
        # chart rather than showing only the smooth interpolated line.
        "ois_node_years": list(discount_curve.node_years),
        "ois_node_discounts": [discount_curve.discount_factor(t) for t in discount_curve.node_years],
        # The OISCurve object itself only retains the resulting discount
        # factors, not the original quoted par rates it was solved from --
        # echoed back here (from the request payload) for the math panel.
        "ois_node_rates": list(ois_rates),
    }


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _row_table_from_cds_curve(cds_curve):
    return [(row["tenor"], row["years"], row["spread_bp"]) for row in cds_curve]


def price(payload: dict) -> dict:
    ois_curve = payload["ois_curve"]
    cds_curve = payload["cds_curve"]
    ois_node_years = [row["years"] for row in ois_curve]
    ois_rates = [row["rate"] for row in ois_curve]
    calibration_recovery = float(payload.get("calibration_recovery", 0.45))

    table = _row_table_from_cds_curve(cds_curve)
    trade_date = _parse_date(payload["trade_date"])
    out = standard_contract.price_standard_contract(
        trade_date=trade_date,
        table=table,
        calibration_recovery=calibration_recovery,
        ois_node_years=ois_node_years,
        ois_rates=ois_rates,
        own_tenor_years=float(payload["tenor_years"]),
        own_coupon=float(payload["coupon_bp"]) / 10000.0,
        own_recovery=float(payload["recovery"]),
        notional=float(payload["notional"]),
    )
    return _serialize_standard(out, [spread_bp for _, _, spread_bp in table], ois_rates, calibration_recovery)


def _serialize_standard(out: dict, spreads_bp, ois_rates, calibration_recovery) -> dict:
    return {
        "contract_type": "standard",
        "trade_date": out["trade_date"].isoformat(),
        "step_in_date": out["step_in_date"].isoformat(),
        "cash_settle_date": out["cash_settle_date"].isoformat(),
        "maturity_date": out["maturity_date"].isoformat(),
        "coupon_bp": out["coupon_bp"],
        "calibration_recovery": calibration_recovery,
        "hazard_nodes": _hazard_node_payload(out["tenors"], spreads_bp, out["hazard_curve"], out["discount_curve"],
                                              out["histories"]),
        "curve_fig": _curve_fig_data(out["hazard_curve"], out["discount_curve"], ois_rates),
        "mtm": out["mtm"],
        "par_spread_bp": out["par_spread_bp"],
        "points_upfront": out["points_upfront"],
        "cash_settlement_amount": out["cash_settlement_amount"],
        "accrued_start_date": out["accrued_start_date"].isoformat(),
        "accrued_end_date": out["accrued_end_date"].isoformat(),
        "accrued_days": out["accrued_days"],
        "schedule": [{
            "period": row["period"],
            "unadjusted": row["unadjusted"].isoformat(),
            "adjusted": row["adjusted"].isoformat(),
            "accrual_delta": row["accrual_delta"],
            "discount_time": row["discount_time"],
            "discount_factor": row["discount_factor"],
            "survival_probability": row["survival_probability"],
        } for row in out["schedule"]],
    }


