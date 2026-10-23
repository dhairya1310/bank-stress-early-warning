"""Rate shock for the top 10 banks on the watchlist, plus the Excel version.

The idea is simple. If rates move, how much do these banks' bond portfolios
lose or gain, and what does that do to their capital? I use duration for this:
the change in value is roughly duration times the rate move times the balance.
It ignores convexity, which is fine for a screen like this but worth noting.
"""
import os
import duckdb
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
import config as c


def treasury_curve(as_of):
    """Gets Treasury yields from FRED as of the latest quarter. If that fails, uses a flat 4%."""
    key = os.getenv("FRED_API_KEY")
    if not key:
        print("No FRED_API_KEY set. Using flat fallback curve.")
        return {t: c.FALLBACK_YIELD for t in c.FRED_SERIES}, "fallback (flat)"
    try:
        from fredapi import Fred
        fred = Fred(api_key=key)
        curve = {}
        for tenor, sid in c.FRED_SERIES.items():
            s = fred.get_series(sid, observation_end=as_of).dropna()
            curve[tenor] = float(s.iloc[-1]) / 100
        return curve, f"FRED H.15 constant maturity, as of {pd.Timestamp(as_of).date()}"
    except Exception as e:
        print(f"FRED pull failed ({type(e).__name__}: {str(e)[:120]}). Using flat fallback curve.")
        return {t: c.FALLBACK_YIELD for t in c.FRED_SERIES}, "fallback (flat)"


def par_mod_duration(y, years, freq=2):
    """Duration of a bond priced at par, which is a fair stand-in for each maturity bucket."""
    n = max(round(years * freq), 1)
    i = y / freq
    return years if y <= 0 else (1 - (1 + i) ** -n) / y


def durations(curve):
    tenors, ylds = zip(*sorted(curve.items()))
    d = {}
    for b, m in c.GOV_MIDPOINT.items():
        d[b] = par_mod_duration(float(np.interp(m, tenors, ylds)), m)
    d.update(c.MBS_DURATION)
    return d


def shock_bank(row, dur, bp):
    dy = bp / 10000
    gov = sum(row[b] * dur[b] for b in c.GOV_MIDPOINT)
    mbs = sum(row[b] * dur[b] for b in c.MBS_DURATION)
    factor = c.DOWN_SHOCK_MBS_FACTOR if dy < 0 else 1.0
    return -dy * (gov + factor * mbs)


if __name__ == "__main__":
    con = duckdb.connect(str(c.DB_PATH))
    latest = con.execute("SELECT MAX(quarter_end) FROM scores").fetchone()[0]
    bucket_cols = ", ".join(f"COALESCE(b.{x}, 0) AS {x}" for x in c.BUCKETS)
    top = con.execute(f"""
        SELECT s.risk_rank, s.name, s.idrssd, s.tier1, s.rwa, s.total_assets,
               COALESCE(s.aoci_optout, 1) AS aoci_optout, s.htm_unreal, s.afs_unreal, {bucket_cols}
        FROM scores s JOIN bank_quarter b USING (idrssd, quarter_end)
        WHERE s.quarter_end = DATE '{latest}' AND s.risk_score IS NOT NULL
        ORDER BY s.risk_rank LIMIT 10""").df()

    curve, curve_src = treasury_curve(latest)
    dur = durations(curve)

    # Run the numbers in Python first. I used these to check the Excel formulas match.
    t = c.TAX_RATE
    top["base_adj_t1"] = top.tier1 + (top.htm_unreal + top.afs_unreal * (top.aoci_optout == 1)) * (1 - t)
    denom = top.rwa.where(top.rwa > 0, top.total_assets)   # smaller banks on the simple leverage rule do not report RWA
    top["ratio_basis"] = np.where(top.rwa > 0, "RWA", "Total assets")
    rows = []
    for name, bp in c.SCENARIOS.items():
        dv = top.apply(lambda r: shock_bank(r, dur, bp), axis=1)
        adj = top.base_adj_t1 + dv * (1 - t)
        rows.append(pd.DataFrame({"scenario": name, "risk_rank": top.risk_rank, "bank": top.name,
                                  "value_change_k": dv.round(0), "adj_tier1_k": adj.round(0),
                                  "adj_tier1_ratio": (adj / denom).round(4),
                                  "ratio_basis": top.ratio_basis}))
    res = pd.concat(rows)
    c.OUT.mkdir(exist_ok=True)
    res.to_csv(c.OUT / "rate_shock_top10.csv", index=False)
    print(f"Curve: {curve_src}")
    print(res.pivot(index="bank", columns="scenario", values="adj_tier1_ratio").round(3).to_string())

    # Now build the same model in Excel so someone can flip scenarios by hand
    wb = Workbook()
    F = "Arial"
    hdr = Font(name=F, bold=True, color="FFFFFF"); hfill = PatternFill("solid", fgColor="1F3864")
    blue = Font(name=F, color="0000FF"); black = Font(name=F); green = Font(name=F, color="008000")
    yellow = PatternFill("solid", fgColor="FFFF00"); bold = Font(name=F, bold=True)
    thin = Border(bottom=Side(style="thin", color="BFBFBF"))
    buckets = list(c.GOV_MIDPOINT) + list(c.MBS_DURATION)
    ng, nb = len(c.GOV_MIDPOINT), len(buckets)

    # Assumptions tab: durations, tax rate and the scenario list
    a = wb.active; a.title = "Assumptions"
    a["A1"] = "Assumptions (blue = input, edit freely)"; a["A1"].font = Font(name=F, bold=True, size=12)
    a["A3"] = "Bucket"; a["A4"] = "Duration (yrs)"; a["A5"] = "Type"
    for j, b in enumerate(buckets):
        col = get_column_letter(2 + j)
        a[f"{col}3"] = b; a[f"{col}3"].font = bold
        a[f"{col}4"] = round(dur[b], 3); a[f"{col}4"].font = blue; a[f"{col}4"].number_format = "0.00"
        a[f"{col}5"] = "Gov/other" if b in c.GOV_MIDPOINT else "Mortgage"; a[f"{col}5"].font = black
    a["B4"].comment = Comment(f"Gov buckets: par bond modified duration at bucket midpoint maturity. "
                              f"Curve: {curve_src}. Mortgage buckets: assumed effective durations.", "model")
    a["A7"] = "Tax rate"; a["B7"] = t
    a["A8"] = "MBS down-shock factor"; a["B8"] = c.DOWN_SHOCK_MBS_FACTOR
    a["C8"] = "Mortgage gains scaled down when rates fall (negative convexity). Assumption."
    for cell in ("B7", "B8"):
        a[cell].font = blue; a[cell].fill = yellow; a[cell].number_format = "0%"
    a["A10"] = "Scenario"; a["B10"] = "Shock (bp)"; a["A10"].font = bold; a["B10"].font = bold
    for i, (name, bp) in enumerate(c.SCENARIOS.items()):
        a[f"A{11 + i}"] = name; a[f"B{11 + i}"] = bp; a[f"B{11 + i}"].font = blue
    last_sc = 10 + len(c.SCENARIOS)
    a["A17"] = "Treasury curve used"; a["A17"].font = bold
    for i, (ten, y) in enumerate(sorted(curve.items())):
        a[f"A{18 + i}"] = f"{ten}y"; a[f"B{18 + i}"] = y
        a[f"B{18 + i}"].number_format = "0.00%"; a[f"B{18 + i}"].font = blue
    a[f"A{18 + len(curve)}"] = f"Source: {curve_src}"
    a.column_dimensions["A"].width = 24
    for j in range(nb):
        a.column_dimensions[get_column_letter(2 + j)].width = 11

    # Model tab: one row per bank, with the scenario dropdown at the top
    m = wb.create_sheet("Model")
    m["A1"] = f"Rate Shock Model: Top 10 Watchlist Banks (as of {pd.Timestamp(latest).date()})"; m["A1"].font = Font(name=F, bold=True, size=13)
    m["A2"] = "Scenario"; m["B2"] = "+200bp"; m["B2"].fill = yellow; m["B2"].font = Font(name=F, bold=True, color="0000FF")
    dv_list = DataValidation(type="list", formula1=f"=Assumptions!$A$11:$A${last_sc}", allow_blank=False)
    m.add_data_validation(dv_list); dv_list.add("B2")
    m["C2"] = "<- pick a scenario"
    m["A3"] = "Shock (decimal)"
    m["B3"] = f"=INDEX(Assumptions!$B$11:$B${last_sc},MATCH($B$2,Assumptions!$A$11:$A${last_sc},0))/10000"
    m["B3"].number_format = "0.00%"; m["B3"].font = green
    m["A4"] = "All dollar amounts in $ thousands (Call Report units)."

    heads = ["Rank", "Bank", "Tier 1", "RWA", "Total assets", "AOCI opt-out", "HTM unreal. G/L",
             "AFS unreal. G/L", "Base adj. Tier 1", "Ratio denominator", "Base adj. T1 ratio",
             "Value change", "After-tax change", "Shocked adj. T1", "Shocked adj. T1 ratio",
             "Change (pp)", "Below threshold?"] + buckets
    H = 6
    for j, h in enumerate(heads):
        cell = m.cell(row=H, column=1 + j, value=h)
        cell.font = hdr; cell.fill = hfill; cell.alignment = Alignment(wrap_text=True, horizontal="center")
    m.row_dimensions[H].height = 32
    bstart = 18  # bucket balances start in column R
    gL, gR = get_column_letter(bstart), get_column_letter(bstart + ng - 1)
    mL, mR = get_column_letter(bstart + ng), get_column_letter(bstart + nb - 1)
    aGL, aGR = get_column_letter(2), get_column_letter(1 + ng)
    aML, aMR = get_column_letter(2 + ng), get_column_letter(1 + nb)

    for i, r in top.reset_index(drop=True).iterrows():
        R = H + 1 + i
        vals = [int(r.risk_rank), r["name"], r.tier1, r.rwa if r.rwa > 0 else None, r.total_assets,
                int(r.aoci_optout), r.htm_unreal, r.afs_unreal]
        for j, v in enumerate(vals):
            cell = m.cell(row=R, column=1 + j, value=None if pd.isna(v) else v)
            cell.font = blue if j >= 2 else black
        for j, b in enumerate(buckets):
            cell = m.cell(row=R, column=bstart + j, value=float(r[b])); cell.font = blue
        m[f"I{R}"] = f"=C{R}+(G{R}+H{R}*F{R})*(1-Assumptions!$B$7)"
        m[f"J{R}"] = f'=IF(AND(ISNUMBER(D{R}),D{R}>0),D{R},E{R})'
        m[f"K{R}"] = f"=IF(J{R}>0,I{R}/J{R},0)"
        m[f"L{R}"] = (f"=-$B$3*(SUMPRODUCT({gL}{R}:{gR}{R},Assumptions!${aGL}$4:${aGR}$4)"
                      f"+IF($B$3<0,Assumptions!$B$8,1)*SUMPRODUCT({mL}{R}:{mR}{R},Assumptions!${aML}$4:${aMR}$4))")
        m[f"M{R}"] = f"=L{R}*(1-Assumptions!$B$7)"
        m[f"N{R}"] = f"=I{R}+M{R}"
        m[f"O{R}"] = f"=IF(J{R}>0,N{R}/J{R},0)"
        m[f"P{R}"] = f"=(O{R}-K{R})*100"
        # 6% is well capitalized on a risk-weighted basis, 5% on a leverage basis
        m[f"Q{R}"] = f'=IF(O{R}<IF(AND(ISNUMBER(D{R}),D{R}>0),0.06,0.05),"YES","no")'
        for col in "IJKLMNOPQ":
            m[f"{col}{R}"].font = black
        for col in "CDEGHIJLMN":
            m[f"{col}{R}"].number_format = "#,##0;(#,##0);-"
        for col in "KO":
            m[f"{col}{R}"].number_format = "0.0%"
        m[f"P{R}"].number_format = "0.0;(0.0);-"
        for j in range(nb):
            m.cell(row=R, column=bstart + j).number_format = "#,##0;(#,##0);-"
        for j in range(len(heads)):
            m.cell(row=R, column=1 + j).border = thin
    lastR = H + len(top)
    m[f"A{lastR + 2}"] = ("Notes: Ratio denominator is RWA, or total assets for community bank leverage ratio "
                          "filers. Base adj. Tier 1 deducts after-tax HTM losses, plus AFS losses for AOCI "
                          "opt-out banks. Below threshold means under 6% on RWA or under 5% on total assets.")
    m[f"A{lastR + 3}"] = "Source: FFIEC Call Reports (RC-B, RC-R), FRED Treasury yields. Blue = inputs, black = formulas."
    widths = {"A": 10, "B": 34}
    for j in range(len(heads)):
        col = get_column_letter(1 + j)
        m.column_dimensions[col].width = widths.get(col, 13)
    m.freeze_panes = "C7"
    for row in m.iter_rows():
        for cell in row:
            if cell.font and cell.font.name != F:
                cell.font = Font(name=F, bold=cell.font.bold, color=cell.font.color, size=cell.font.size)
    wb.move_sheet("Model", offset=-1)
    xl = c.OUT / "rate_shock_model.xlsx"
    wb.save(xl)
    print(f"Saved {xl}")
