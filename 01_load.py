"""Loads the quarterly Call Reports and the FDIC failed bank list into DuckDB.

The FFIEC bulk files come as one zip per quarter with a text file for each
schedule. I only pull the columns listed in config.py, line them up by bank,
and stack all the quarters into one table."""
import io, re, zipfile
from collections import defaultdict
import duckdb
import pandas as pd
import config as c

ALL = {**c.FIELDS, **c.BUCKETS}
NEEDED = {code for codes in ALL.values() for code in codes}
POR_COLS = {"IDRSSD": "idrssd", "Financial Institution Name": "name",
            "FDIC Certificate Number": "cert", "Financial Institution State": "state"}


def iter_files():
    """Goes through the folder and hands back every text file, whether it is still zipped or not."""
    for p in sorted(c.CALL_DIR.rglob("*")):
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.lower().endswith(".txt"):
                        yield n, z.read(n)
        elif p.suffix.lower() == ".txt":
            yield p.name, p.read_bytes()


def quarter_of(name):
    m = re.search(r"(\d{2})(\d{2})(\d{4})", name)
    return pd.Timestamp(f"{m.group(3)}-{m.group(1)}-{m.group(2)}") if m else None


def read_schedule(raw, keep):
    df = pd.read_csv(io.BytesIO(raw), sep="\t", dtype=str, skiprows=[1],
                     encoding="latin-1", low_memory=False,
                     usecols=lambda col: col.strip().strip('"') in keep)
    df.columns = [x.strip().strip('"') for x in df.columns]
    return df.set_index("IDRSSD")


def load_call_reports():
    by_q = defaultdict(list)
    for name, raw in iter_files():
        q = quarter_of(name)
        if q is not None and q >= pd.Timestamp(c.START_QUARTER):
            by_q[q].append((name, raw))
    if not by_q:
        raise SystemExit(f"No Call Report files found in {c.CALL_DIR}")

    frames = []
    for q, files in sorted(by_q.items()):
        parts, por = [], None
        for name, raw in files:
            if "POR" in name.upper():
                por = read_schedule(raw, set(POR_COLS))
            elif "SCHEDULE" in name.upper():
                part = read_schedule(raw, NEEDED | {"IDRSSD"})
                if part.shape[1]:
                    parts.append(part)
        wide = pd.concat(parts, axis=1)
        wide = wide.loc[:, ~wide.columns.duplicated()]
        wide = wide.apply(pd.to_numeric, errors="coerce")

        out = pd.DataFrame(index=wide.index)
        for field, codes in ALL.items():
            present = [x for x in codes if x in wide.columns]
            out[field] = wide[present].bfill(axis=1).iloc[:, 0] if present else pd.NA
            if not present and field not in c.OPTIONAL:
                print(f"  WARNING {q.date()}: no column for {field} {codes}")
        if por is not None:
            out = out.join(por.rename(columns=POR_COLS).drop(columns="idrssd", errors="ignore"))
        out["quarter_end"] = q
        frames.append(out.reset_index().rename(columns={"IDRSSD": "idrssd"}))
        print(f"{q.date()}: {len(out):,} banks")

    df = pd.concat(frames, ignore_index=True)
    df["idrssd"] = pd.to_numeric(df["idrssd"], errors="coerce").astype("Int64")
    df["cert"] = pd.to_numeric(df.get("cert"), errors="coerce").astype("Int64")
    for col in list(ALL):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df


def load_failures():
    for enc in ("utf-8-sig", "cp1252"):
        try:
            f = pd.read_csv(c.FAILED_BANKS_CSV, dtype=str, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    f.columns = [re.sub(r"\W+", "_", x.replace("\xa0", " ").strip().lower()).strip("_")
                 for x in f.columns]
    f = f.rename(columns={"closing_date": "closing_date", "cert": "cert"})
    f["cert"] = pd.to_numeric(f["cert"], errors="coerce").astype("Int64")
    f["closing_date"] = pd.to_datetime(f["closing_date"].str.strip(), format="mixed")
    return f


if __name__ == "__main__":
    c.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    bq = load_call_reports()
    fb = load_failures()
    con = duckdb.connect(str(c.DB_PATH))
    con.execute("CREATE OR REPLACE TABLE bank_quarter AS SELECT * FROM bq")
    con.execute("CREATE OR REPLACE TABLE failed_banks AS SELECT * FROM fb")
    n = con.execute(f"SELECT COUNT(*) FROM bank_quarter WHERE total_assets >= {c.ASSET_FLOOR}").fetchone()[0]
    print(f"Loaded {len(bq):,} bank-quarters ({n:,} over $1B) and {len(fb):,} failures")
