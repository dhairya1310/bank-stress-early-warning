"""Builds clean, Tableau-ready CSVs for the dashboard.

Tableau works best with long, tidy tables, so this reshapes the results into four
files in output/tableau. Each one feeds one sheet of the dashboard.
"""
import duckdb
import pandas as pd
import config as c

con = duckdb.connect(str(c.DB_PATH))
out = c.OUT / "tableau"
out.mkdir(parents=True, exist_ok=True)
latest = con.execute("SELECT MAX(quarter_end) FROM scores").fetchone()[0]

# 1. Watchlist: every scored bank in the latest quarter, with the metrics shown as percents
watch = con.execute(f"""
    SELECT risk_rank AS "Rank", name AS "Bank", state AS "State",
           ROUND(total_assets / 1e6, 2)          AS "Assets ($B)",
           ROUND(risk_score, 1)                  AS "Risk Score",
           ROUND(100 * uninsured_ratio, 1)       AS "Uninsured Deposits %",
           ROUND(100 * unreal_loss_pct_t1, 1)    AS "Unrealized Loss % of Tier 1",
           ROUND(100 * adj_tier1_lev, 1)         AS "Adj. Tier 1 Leverage %",
           ROUND(100 * liq_coverage, 1)          AS "Liquidity Coverage %",
           ROUND(100 * cre_conc, 0)              AS "CRE % of Capital",
           CASE WHEN cre_flag THEN 'Yes' ELSE 'No' END AS "CRE Over 300%",
           ROUND(100 * dep_change_qoq, 1)        AS "Deposit Change QoQ %",
           CASE WHEN risk_rank <= 10 THEN 'Top 10'
                WHEN risk_rank <= 50 THEN 'Top 50' ELSE 'Rest' END AS "Tier"
    FROM scores
    WHERE quarter_end = DATE '{latest}' AND risk_score IS NOT NULL
    ORDER BY risk_rank""").df()
watch.to_csv(out / "1_watchlist.csv", index=False)

# 2. Trends: how the metrics moved for today's top 10, the four failed banks,
#    and the median bank, so the lines have something to be compared against
top10 = con.execute(f"""SELECT idrssd FROM scores
    WHERE quarter_end = DATE '{latest}' ORDER BY risk_rank LIMIT 10""").df().idrssd.tolist()
failed = con.execute("""SELECT DISTINCT s.idrssd FROM scores s
    JOIN failed_banks f ON f.cert = s.cert
    WHERE f.closing_date >= DATE '2023-01-01'""").df().idrssd.tolist()
metrics = {"risk_score": ("Risk Score", 1), "uninsured_ratio": ("Uninsured Deposits %", 100),
           "unreal_loss_pct_t1": ("Unrealized Loss % of Tier 1", 100),
           "adj_tier1_lev": ("Adj. Tier 1 Leverage %", 100),
           "liq_coverage": ("Liquidity Coverage %", 100), "cre_conc": ("CRE % of Capital", 100),
           "dep_change_qoq": ("Deposit Change QoQ %", 100)}
cols = ", ".join(metrics)
ids = ", ".join(str(i) for i in top10 + failed) or "NULL"
banks = con.execute(f"""SELECT quarter_end, name, idrssd, {cols}
    FROM scores WHERE idrssd IN ({ids})""").df()
banks["Group"] = banks.idrssd.map(lambda i: "Failed bank" if i in failed else "Current top 10")
med = con.execute(f"""SELECT quarter_end, 'Median bank' AS name, NULL AS idrssd,
    {", ".join(f"MEDIAN({m}) AS {m}" for m in metrics)}
    FROM scores WHERE risk_score IS NOT NULL GROUP BY quarter_end""").df()
med["Group"] = "Median bank"
trend = pd.concat([banks, med]).melt(id_vars=["quarter_end", "name", "idrssd", "Group"],
                                     value_vars=list(metrics), var_name="m", value_name="v")
trend["Metric"] = trend.m.map(lambda m: metrics[m][0])
trend["Value"] = (trend.v * trend.m.map(lambda m: metrics[m][1])).round(2)
trend = trend.rename(columns={"quarter_end": "Quarter", "name": "Bank"})
trend[["Quarter", "Bank", "Group", "Metric", "Value"]].dropna(subset=["Value"]) \
    .to_csv(out / "2_trends.csv", index=False)

# 3. Backtest: every bank scored at the end of 2022, with the ones that failed marked.
#    Plotting all of them shows the failures sitting at the top of the pile.
bt = con.execute(f"""
    SELECT s.risk_rank AS "Rank", s.name AS "Bank", ROUND(s.risk_score, 1) AS "Risk Score",
           ROUND(s.total_assets / 1e6, 2) AS "Assets ($B)",
           ROUND(100.0 * (1 - (s.risk_rank - 1) / s.n_scored), 1) AS "Percentile",
           CASE WHEN f.cert IS NOT NULL THEN 'Failed' ELSE 'Survived' END AS "Outcome",
           f.closing_date AS "Closing Date"
    FROM scores s
    LEFT JOIN failed_banks f ON f.cert = s.cert AND f.closing_date >= DATE '2023-01-01'
    WHERE s.quarter_end = DATE '{c.BACKTEST_QUARTER}' AND s.risk_score IS NOT NULL
    ORDER BY s.risk_rank""").df()
bt.to_csv(out / "3_backtest_2022q4.csv", index=False)

# 4. Rate shock: one row per bank per scenario, ratio shown as a percent
rs = pd.read_csv(c.OUT / "rate_shock_top10.csv")
rs["Adj. Tier 1 Ratio %"] = (100 * rs.adj_tier1_ratio).round(2)
rs["Value Change ($M)"] = (rs.value_change_k / 1000).round(1)
rs["Threshold %"] = rs.ratio_basis.map({"RWA": 6.0, "Total assets": 5.0})
rs = rs.rename(columns={"scenario": "Scenario", "bank": "Bank", "risk_rank": "Rank",
                        "ratio_basis": "Ratio Basis"})
rs[["Rank", "Bank", "Scenario", "Adj. Tier 1 Ratio %", "Value Change ($M)", "Ratio Basis",
    "Threshold %"]].to_csv(out / "4_rate_shock.csv", index=False)

for f in sorted(out.glob("*.csv")):
    print(f"{f.name}: {sum(1 for _ in open(f)) - 1:,} rows")
