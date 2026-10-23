"""All the settings for the project live here.

If you want to change a path, a field code or an assumption, do it in this file
so the scripts stay untouched."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
CALL_DIR = RAW / "call_reports"          # drop the quarterly FFIEC zips in here
FAILED_BANKS_CSV = RAW / "banklist.csv"  # downloaded from the FDIC failed bank page
MDRM_CSV = RAW / "MDRM_CSV.csv"          # the Fed's data dictionary, used to check field codes
DB_PATH = ROOT / "data" / "bank_ews.duckdb"
OUT = ROOT / "output"

START_QUARTER = "2019-12-31"
ASSET_FLOOR = 1_000_000      # Call Reports are in thousands, so this means $1B
TAX_RATE = 0.21
CRE_LIMIT = 3.00             # regulators start asking questions above 300% of capital
CONSTRUCTION_LIMIT = 1.00    # same idea for construction loans, at 100%
FILING_LAG_DAYS = 45         # banks file about 30 days after quarter end, 45 gives some buffer
BACKTEST_QUARTER = "2022-12-31"
TOP_N = [10, 25, 50, 100]

# Each field maps to one or more Call Report codes. The first one that has a value wins.
# Big banks with foreign offices file the 031 form and use RCFD or RCFA codes.
# Everyone else files the 041 or 051 form and uses RCON or RCOA codes.
# I checked these against the MDRM dictionary with 00_verify_fields.py.
FIELDS = {
    "total_assets":   ["RCFD2170", "RCON2170"],
    "deposits_dom":   ["RCON2200"],
    "deposits_for":   ["RCFN2200"],
    "uninsured_dep":  ["RCON5597"],                 # RC-O Memo 2
    "htm_amort":      ["RCFD1754", "RCON1754"],     # RC-B
    "htm_fv":         ["RCFD1771", "RCON1771"],
    "afs_amort":      ["RCFD1772", "RCON1772"],
    "afs_fv":         ["RCFD1773", "RCON1773"],
    "pledged_sec":    ["RCFD0416", "RCON0416"],     # RC-B Memo 1
    "cash_nonint":    ["RCFD0081", "RCON0081"],     # RC item 1.a
    "cash_int":       ["RCFD0071", "RCON0071"],     # RC item 1.b
    "tier1":          ["RCFA8274", "RCOA8274"],     # RC-R Part I
    "total_cap":      ["RCFA3792", "RCOA3792"],     # RC-R Part II
    "rwa":            ["RCFAA223", "RCOAA223"],     # null for CBLR banks
    "aoci_optout":    ["RCOAP838"],               # 1 = opted out of AOCI in capital
    "constr_14":      ["RCONF158"],                 # RC-C 1.a.1
    "constr_other":   ["RCONF159"],                 # RC-C 1.a.2
    "multifamily":    ["RCON1460"],                 # RC-C 1.d
    "nfnr_owner":     ["RCONF160"],                 # RC-C 1.e.1
    "nfnr_nonowner":  ["RCONF161"],                 # RC-C 1.e.2
    "cre_unsecured":  ["RCFD2746", "RCON2746"],     # RC-C Memo: CRE loans not secured by RE
}
# Securities broken out by how long until they mature or reprice (RC-B, Memo 2).
# Banks report HTM at amortized cost and AFS at fair value here.
BUCKETS = {
    # Treasuries, agencies, munis and other non-mortgage bonds
    "gov_0_3m":  ["RCFDA549", "RCONA549"], "gov_3_12m": ["RCFDA550", "RCONA550"],
    "gov_1_3y":  ["RCFDA551", "RCONA551"], "gov_3_5y":  ["RCFDA552", "RCONA552"],
    "gov_5_15y": ["RCFDA553", "RCONA553"], "gov_15y":   ["RCFDA554", "RCONA554"],
    # plain residential mortgage-backed securities
    "mbs_0_3m":  ["RCFDA555", "RCONA555"], "mbs_3_12m": ["RCFDA556", "RCONA556"],
    "mbs_1_3y":  ["RCFDA557", "RCONA557"], "mbs_3_5y":  ["RCFDA558", "RCONA558"],
    "mbs_5_15y": ["RCFDA559", "RCONA559"], "mbs_15y":   ["RCFDA560", "RCONA560"],
    # CMOs and other mortgage securities, split by expected average life
    "cmo_0_3y":  ["RCFDA561", "RCONA561"], "cmo_3y":    ["RCFDA562", "RCONA562"],
}
OPTIONAL = {"cre_unsecured", "aoci_optout", "pledged_sec", "deposits_for"}

# For the non-mortgage buckets I use the middle of each maturity range.
# Duration then comes from the Treasury curve pulled from FRED.
GOV_MIDPOINT = {"gov_0_3m": 0.125, "gov_3_12m": 0.625, "gov_1_3y": 2, "gov_3_5y": 4,
                "gov_5_15y": 10, "gov_15y": 20}
# Mortgage bonds get prepaid early, so their real duration is shorter than their maturity.
# These numbers are my assumptions and they are listed as a limitation in the README.
MBS_DURATION = {"mbs_0_3m": 0.1, "mbs_3_12m": 0.5, "mbs_1_3y": 1.7, "mbs_3_5y": 3.0,
                "mbs_5_15y": 4.5, "mbs_15y": 6.0, "cmo_0_3y": 1.5, "cmo_3y": 4.5}
FALLBACK_YIELD = 0.04        # only used if FRED cannot be reached
DOWN_SHOCK_MBS_FACTOR = 0.6  # when rates fall people refinance, so mortgage bonds gain less than they lose
SCENARIOS = {"Base": 0, "+100bp": 100, "+200bp": 200, "-100bp": -100}
FRED_SERIES = {0.25: "DGS3MO", 1: "DGS1", 2: "DGS2", 5: "DGS5", 10: "DGS10", 30: "DGS30"}

# Metrics that feed the risk score, with a weight and a direction.
# "high" means a bigger number is worse. "low" means a smaller number is worse.
# Equal weights to start, so nobody can say I tuned them to fit the 2023 failures.
SCORE_METRICS = {
    "uninsured_ratio":     (1.0, "high"),
    "unreal_loss_pct_t1":  (1.0, "high"),
    "adj_tier1_lev":       (1.0, "low"),
    "liq_coverage":        (1.0, "low"),
    "cre_conc":            (1.0, "high"),
    "dep_change_qoq":      (1.0, "low"),
}
MIN_METRICS = 5   # skip banks missing too much data. In practice this means a bank
                  # needs uninsured deposit data, which is the whole point of the screen.
