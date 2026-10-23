"""Runs every step in order. Use this after the data is in place."""
import runpy
for step in ["01_load.py", "02_metrics.py", "03_backtest.py", "04_rate_shock.py"]:
    print(f"\n===== {step} =====")
    runpy.run_path(step, run_name="__main__")
