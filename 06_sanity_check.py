"""Sanity check: compare the pipeline's numbers for well-known banks against the public record.

If our numbers for SVB and Signature at the end of 2022 land close to what the
Fed and FDIC reported after the failures, the Call Report fields are being read
correctly. Then it prints the raw inputs behind the watchlist banks named in the
memo, so each one can be checked against its filing on the FFIEC site.
"""
import duckdb
import config as c

con = duckdb.connect(str(c.DB_PATH))
pct = lambda x: "n/a" if x is None else f"{100 * x:.1f}%"

print("1. FAILED BANKS AT 2022 Q4 (compare with the public record)\n")
rows = con.execute(f"""
    SELECT m.name, m.total_assets, m.total_deposits, m.uninsured_dep, m.uninsured_ratio,
           m.htm_unreal, m.afs_unreal, m.tier1
    FROM metrics m JOIN failed_banks f ON f.cert = m.cert
    WHERE m.quarter_end = DATE '{c.BACKTEST_QUARTER}' AND f.closing_date >= DATE '2023-01-01'
    ORDER BY m.total_assets DESC""").fetchall()
for name, ta, dep, unins, ratio, htm, afs, t1 in rows:
    print(f"{name}")
    print(f"   total assets      ${ta / 1e6:,.1f}B")
    print(f"   deposits          ${dep / 1e6:,.1f}B")
    print(f"   uninsured         ${unins / 1e6:,.1f}B  ({pct(ratio)})")
    print(f"   HTM unrealized    ${htm / 1e6:,.1f}B")
    print(f"   AFS unrealized    ${afs / 1e6:,.1f}B")
    print(f"   Tier 1 capital    ${t1 / 1e6:,.1f}B\n")
print("Public record, approximate, end of 2022:")
print("   SVB: about $209B assets, $173B deposits, about 94% uninsured, about $15B HTM unrealized loss")
print("   Signature: about $110B assets, about 90% uninsured")
print("If these are far off, a field is being read wrong.\n")

print("2. WATCHLIST BANKS NAMED IN THE MEMO (check each against its FFIEC filing)\n")
latest = con.execute("SELECT MAX(quarter_end) FROM metrics").fetchone()[0]
names = ["READING CO-OPERATIVE BANK", "INDEPENDENCE BANK OF KENTUCKY",
         "FIRST HAWAIIAN BANK", "AMERICAN NATIONAL BANK OF TEXAS, THE", "SIMMONS BANK"]
for n in names:
    r = con.execute(f"""
        SELECT m.name, m.idrssd, m.total_assets, m.cash, b.afs_fv, b.htm_fv, b.pledged_sec,
               m.uninsured_dep, m.liq_coverage, m.tier1, m.adj_tier1_lev
        FROM metrics m JOIN bank_quarter b USING (idrssd, quarter_end)
        WHERE m.quarter_end = DATE '{latest}' AND m.name = ?""", [n]).fetchone()
    if not r:
        print(f"{n}: not found\n"); continue
    name, rssd, ta, cash, afs, htm, pledged, unins, liq, t1, lev = r
    k = lambda x: "n/a" if x is None else f"${x:,.0f}K"
    print(f"{name}  (RSSD {rssd})")
    print(f"   total assets {k(ta)} | cash {k(cash)} | AFS fair value {k(afs)} | HTM fair value {k(htm)}")
    print(f"   pledged securities {k(pledged)} | uninsured deposits {k(unins)} | Tier 1 {k(t1)}")
    print(f"   liquidity coverage {pct(liq)} | adjusted Tier 1 leverage {pct(lev)}\n")
print("Look up each RSSD on the FFIEC CDR site (Public Data Distribution, search by RSSD)")
print("and compare these inputs with Schedules RC, RC-B, RC-O and RC-R in the 2026 Q2 report.")
