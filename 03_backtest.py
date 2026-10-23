"""Backtest: would this score have flagged the banks that actually failed?

I check two things. First, where each failed bank ranked at the end of 2022,
before SVB went down. Second, where each one ranked in its last filing before
it closed, using only data that was public at the time."""
import duckdb
import config as c

con = duckdb.connect(str(c.DB_PATH))
c.OUT.mkdir(exist_ok=True)
lines = []

# Pull every failure since 2023 and find where it ranked before it closed
fails = con.execute(f"""
    WITH f AS (SELECT * FROM failed_banks WHERE closing_date >= DATE '2023-01-01'),
    -- find the last Call Report each failed bank filed before it closed
    last_filing AS (
        SELECT f.bank_name, f.cert, f.closing_date, b.quarter_end,
               ROW_NUMBER() OVER (PARTITION BY f.cert ORDER BY b.quarter_end DESC) AS rn
        FROM f JOIN bank_quarter b ON b.cert = f.cert
        WHERE b.quarter_end + INTERVAL {c.FILING_LAG_DAYS} DAY < f.closing_date
    ),
    -- only keep it if the bank was still over $1B in that filing
    pit AS (
        SELECT l.bank_name, l.cert, l.closing_date, s.quarter_end, s.risk_score, s.risk_rank,
               s.n_scored, l.rn
        FROM last_filing l
        JOIN scores s ON s.cert = l.cert AND s.quarter_end = l.quarter_end
        WHERE l.rn = 1 AND s.risk_score IS NOT NULL
    ),
    fixed AS (
        SELECT cert, risk_score AS score_bt, risk_rank AS rank_bt, n_scored AS n_bt
        FROM scores WHERE quarter_end = DATE '{c.BACKTEST_QUARTER}'
    )
    SELECT p.bank_name, p.closing_date,
           p.quarter_end AS pit_quarter, ROUND(p.risk_score, 1) AS pit_score,
           p.risk_rank AS pit_rank, p.n_scored AS pit_n,
           ROUND(100.0 * (1 - (p.risk_rank - 1) / p.n_scored), 1) AS pit_percentile,
           ROUND(x.score_bt, 1) AS score_{c.BACKTEST_QUARTER[:4]}q4, x.rank_bt AS rank_{c.BACKTEST_QUARTER[:4]}q4
    FROM pit p LEFT JOIN fixed x USING (cert)
    WHERE p.rn = 1 ORDER BY p.closing_date""").df()
fails.to_csv(c.OUT / "backtest_failures.csv", index=False)

n_bt = con.execute(f"SELECT COUNT(risk_score) FROM scores WHERE quarter_end = DATE '{c.BACKTEST_QUARTER}'").fetchone()[0]
lines.append(f"BACKTEST as of {c.BACKTEST_QUARTER} ({n_bt:,} banks over $1B scored)")
lines.append(f"Failures since 2023 that were over $1B: {len(fails)}\n")
lines.append(fails.to_string(index=False))

# How many failures landed in the top 10, 25, 50 and 100 at the end of 2022
rank_col = f"rank_{c.BACKTEST_QUARTER[:4]}q4"
lines.append("\nTop-N capture (fixed snapshot):")
for n in c.TOP_N:
    hits = int((fails[rank_col] <= n).sum())
    base = len(fails) / n_bt if n_bt else 0
    lines.append(f"  Top {n:>3}: {hits} of {len(fails)} failures caught | "
                 f"precision {hits / n:.1%} vs {base:.1%} random | false positives {n - hits}")

# Banks I flagged that did not fail. Worth a look, some may have been sold or rescued.
fp = con.execute(f"""
    SELECT s.risk_rank, s.name, s.state, ROUND(s.total_assets / 1e6, 1) AS assets_bn,
           ROUND(s.risk_score, 1) AS risk_score
    FROM scores s
    WHERE s.quarter_end = DATE '{c.BACKTEST_QUARTER}' AND s.risk_rank <= 25
      AND s.cert NOT IN (SELECT cert FROM failed_banks WHERE cert IS NOT NULL)
    ORDER BY s.risk_rank""").df()
fp.to_csv(c.OUT / "backtest_false_positives_top25.csv", index=False)
lines.append(f"\nTop 25 banks that did NOT fail: {len(fp)}. Check which were acquired, "
             "raised capital, or cut dividends in 2023. Those are 'near misses', not pure noise.")
lines.append("\nCaveat: very few failures over $1B. Treat this as a sanity check, not proof.")

report = "\n".join(lines)
(c.OUT / "backtest_summary.txt").write_text(report)
print(report)
