"""Builds the risk metrics and turns them into one score per bank per quarter.

The metrics themselves are in sql/metrics.sql. This script runs that file, ranks
each metric against all other banks in the same quarter, and averages the ranks.
Ranking within a quarter matters, since 2022 losses were high for everyone."""
import duckdb
import config as c

con = duckdb.connect(str(c.DB_PATH))
sql = (c.ROOT / "sql" / "metrics.sql").read_text().format(
    asset_floor=c.ASSET_FLOOR, tax=c.TAX_RATE,
    cre_limit=c.CRE_LIMIT, constr_limit=c.CONSTRUCTION_LIMIT)
con.execute(sql)

# Rank each metric within its quarter. A 1.0 means the worst bank that quarter.
# Banks missing a metric are left out of that ranking instead of being treated as safe.
pct_cols, num, den, cnt = [], [], [], []
for m, (w, direction) in c.SCORE_METRICS.items():
    order = "ASC" if direction == "high" else "DESC"
    pct_cols.append(
        f"CASE WHEN {m} IS NULL THEN NULL ELSE PERCENT_RANK() OVER "
        f"(PARTITION BY quarter_end, {m} IS NULL ORDER BY {m} {order}) END AS p_{m}")
    num.append(f"COALESCE({w} * p_{m}, 0)")
    den.append(f"CASE WHEN p_{m} IS NOT NULL THEN {w} ELSE 0 END")
    cnt.append(f"CASE WHEN p_{m} IS NOT NULL THEN 1 ELSE 0 END")

con.execute(f"""
CREATE OR REPLACE TABLE scores AS
WITH p AS (SELECT *, {", ".join(pct_cols)} FROM metrics)
SELECT *,
    {" + ".join(cnt)} AS n_metrics,
    CASE WHEN {" + ".join(cnt)} >= {c.MIN_METRICS}
         THEN 100 * ({" + ".join(num)}) / NULLIF({" + ".join(den)}, 0) END AS risk_score
FROM p;

CREATE OR REPLACE TABLE scores AS
SELECT *, RANK() OVER (PARTITION BY quarter_end ORDER BY risk_score DESC NULLS LAST) AS risk_rank,
       COUNT(risk_score) OVER (PARTITION BY quarter_end) AS n_scored
FROM scores;
""")

c.OUT.mkdir(exist_ok=True)
latest = con.execute("SELECT MAX(quarter_end) FROM scores").fetchone()[0]
watch = con.execute(f"""
    SELECT risk_rank, name, state, idrssd, quarter_end,
           ROUND(total_assets / 1e6, 1)        AS assets_bn,
           ROUND(risk_score, 1)                AS risk_score,
           ROUND(100 * uninsured_ratio, 1)     AS uninsured_pct,
           ROUND(100 * unreal_loss_pct_t1, 1)  AS unreal_loss_pct_t1,
           ROUND(100 * adj_tier1_lev, 1)       AS adj_tier1_lev_pct,
           ROUND(100 * adj_tier1_ratio, 1)     AS adj_tier1_rwa_pct,
           ROUND(100 * liq_coverage, 1)        AS liq_coverage_pct,
           ROUND(100 * cre_conc, 0)            AS cre_conc_pct,
           cre_flag,
           ROUND(100 * dep_change_qoq, 1)      AS dep_change_qoq_pct,
           n_metrics
    FROM scores WHERE quarter_end = DATE '{latest}' AND risk_score IS NOT NULL
    ORDER BY risk_rank""").df()
watch.to_csv(c.OUT / "watchlist_latest.csv", index=False)
con.execute(f"COPY scores TO '{c.OUT / 'scores_all_quarters.csv'}' (HEADER)")
print(f"Scored {len(watch):,} banks as of {latest}. Top 10:")
print(watch.head(10)[["risk_rank", "name", "assets_bn", "risk_score"]].to_string(index=False))
