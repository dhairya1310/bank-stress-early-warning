# Setup and Run

## 1. Install
pip install -r requirements.txt

## 2. Download data into data/raw/
| File | Where | Save as |
|---|---|---|
| Call Reports, 2019 Q4 to latest | FFIEC CDR Bulk Data Download: "Call Reports -- Single Period", tab delimited, one zip per quarter | data/raw/call_reports/ (leave zips as is) |
| Failed Bank List | FDIC Bank Failures page, CSV | data/raw/banklist.csv |
| MDRM dictionary | Federal Reserve MDRM download, CSV | data/raw/MDRM_CSV.csv |

## 3. Free FRED API key
Get one at fred.stlouisfed.org, then set it:
- Mac/Linux: export FRED_API_KEY=your_key
- Windows: setx FRED_API_KEY your_key
Without a key the rate shock uses a flat 4% curve.

## 4. Run
python 00_verify_fields.py   # every code should say OK. Fix config.py if not.
python run_all.py

## 5. Outputs (output/)
- watchlist_latest.csv: current ranked watchlist
- scores_all_quarters.csv: feed for Power BI
- backtest_summary.txt, backtest_failures.csv, backtest_false_positives_top25.csv
- rate_shock_top10.csv, rate_shock_model.xlsx (scenario dropdown on the Model sheet)

## Test without real data
python tests/make_mock_data.py data/raw
python run_all.py
Delete data/ before loading real files.
