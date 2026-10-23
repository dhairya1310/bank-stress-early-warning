"""Checks every field code in config.py against the Fed's MDRM dictionary.

Run this first. If a code shows MISSING or has an old end date, fix it before
running anything else, because a wrong code quietly turns into empty data."""
import pandas as pd
import config as c

mdrm = pd.read_csv(c.MDRM_CSV, skiprows=1, dtype=str, encoding="latin-1")
mdrm.columns = [x.strip() for x in mdrm.columns]
mdrm["code"] = mdrm["Mnemonic"].str.strip() + mdrm["Item Code"].str.strip()
mdrm = mdrm.drop_duplicates("code", keep="last").set_index("code")

rows = []
for field, codes in {**c.FIELDS, **c.BUCKETS}.items():
    for code in codes:
        if code in mdrm.index:
            r = mdrm.loc[code]
            rows.append((field, code, "OK", r["Item Name"][:70], r["End Date"][:10]))
        else:
            rows.append((field, code, "MISSING", "", ""))
out = pd.DataFrame(rows, columns=["field", "code", "status", "item_name", "end_date"])
pd.set_option("display.width", 200, "display.max_rows", 200)
print(out.to_string(index=False))
bad = out[out.status == "MISSING"]
print(f"\n{len(bad)} codes missing. End dates before 9999 mean the item was retired.")
