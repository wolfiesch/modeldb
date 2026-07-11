"""Promotion layer: turns resolved source_model_records into canonical
`model` rows and typed facts (`price_component`, `benchmark_result`).

Runtime order (see pipeline.py):
    build_spine -> resolve -> promote_prices -> promote_benchmarks
"""
