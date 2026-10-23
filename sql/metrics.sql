-- Risk metrics for every bank over $1B, every quarter.
-- Dollar amounts are in thousands, same as the Call Reports.
-- The values in curly braces get filled in from config.py when 02_metrics.py runs.
CREATE OR REPLACE TABLE metrics AS
WITH base AS (
    SELECT
        *,
        COALESCE(deposits_dom, 0) + COALESCE(deposits_for, 0)          AS total_deposits,
        COALESCE(cash_nonint, 0) + COALESCE(cash_int, 0)               AS cash,
        COALESCE(htm_fv, 0) - COALESCE(htm_amort, 0)                   AS htm_unreal,
        COALESCE(afs_fv, 0) - COALESCE(afs_amort, 0)                   AS afs_unreal,
        COALESCE(constr_14, 0) + COALESCE(constr_other, 0)             AS construction,
        COALESCE(constr_14, 0) + COALESCE(constr_other, 0) + COALESCE(multifamily, 0)
          + COALESCE(nfnr_nonowner, 0) + COALESCE(cre_unsecured, 0)    AS cre_total
    FROM bank_quarter
),
lagged AS (
    -- get last quarter's deposits before filtering, so a bank that just crossed $1B still has a prior quarter
    SELECT
        *,
        LAG(total_deposits) OVER w AS prev_deposits,
        LAG(quarter_end)    OVER w AS prev_quarter
    FROM base
    WINDOW w AS (PARTITION BY idrssd ORDER BY quarter_end)
)
SELECT
    idrssd, cert, name, state, quarter_end,
    total_assets, total_deposits, uninsured_dep, cash,
    htm_amort, htm_fv, afs_amort, afs_fv, htm_unreal, afs_unreal,
    tier1, total_cap, rwa, aoci_optout, cre_total, construction,

    -- How much of the deposit base is above the FDIC limit. This money runs first.
    uninsured_dep / NULLIF(total_deposits, 0)                                  AS uninsured_ratio,

    -- Paper losses on the bond book after tax, compared to Tier 1 capital
    GREATEST(-(htm_unreal + afs_unreal), 0) * (1 - {tax}) / NULLIF(tier1, 0)   AS unreal_loss_pct_t1,

    -- What the Tier 1 ratio would look like if the bank had to recognize its bond losses.
    -- HTM losses never hit regulatory capital. Most banks also opted out of counting AFS
    -- losses, so for them I take both out. This is exactly the gap that sank SVB.
    (tier1 + (htm_unreal + CASE WHEN COALESCE(aoci_optout, 1) = 1 THEN afs_unreal ELSE 0 END)
              * (1 - {tax})) / NULLIF(rwa, 0)                                  AS adj_tier1_ratio,
    tier1 / NULLIF(rwa, 0)                                                     AS tier1_ratio,

    -- Same adjustment, but over total assets. Every bank reports what this needs, including
    -- small banks on the simple leverage rule, so this is the one that goes into the score.
    (tier1 + (htm_unreal + CASE WHEN COALESCE(aoci_optout, 1) = 1 THEN afs_unreal ELSE 0 END)
              * (1 - {tax})) / NULLIF(total_assets, 0)                         AS adj_tier1_lev,

    -- If uninsured depositors all left, could cash plus unpledged bonds cover them?
    (cash + GREATEST(COALESCE(afs_fv, 0) + COALESCE(htm_fv, 0) - COALESCE(pledged_sec, 0), 0))
        / NULLIF(uninsured_dep, 0)                                             AS liq_coverage,

    -- Commercial real estate exposure compared to capital, plus the regulator red flags.
    -- Small banks on the leverage rule do not report total capital, so Tier 1 stands in.
    cre_total / NULLIF(COALESCE(total_cap, tier1), 0)                          AS cre_conc,
    cre_total / NULLIF(COALESCE(total_cap, tier1), 0) > {cre_limit}            AS cre_flag,
    construction / NULLIF(COALESCE(total_cap, tier1), 0) > {constr_limit}      AS construction_flag,

    -- Deposit change from last quarter. Skipped if the bank has a gap in its filings.
    CASE WHEN date_diff('day', prev_quarter, quarter_end) <= 100
         THEN total_deposits / NULLIF(prev_deposits, 0) - 1 END               AS dep_change_qoq
FROM lagged
WHERE total_assets >= {asset_floor};
