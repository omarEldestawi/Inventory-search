import pandas as pd
import pytest

from src.catalog_diagnostics import CatalogResult, FileFingerprint, ImportDiagnostics
from src.pipeline import PipelineExecutionError, run_procurement_pipeline


def test_reviewed_partial_catalog_reaches_procurement_and_is_revalidated(tmp_path):
    catalog = tmp_path / "supplier.csv"
    catalog.write_text("Item Name,Public Price,Discount\nPanadol Extra 500mg Tablet,100,20%\n")
    order = tmp_path / "order.csv"
    order.write_text("Item Name,Quantity\nPanadol Extra 500mg Tablet,4\n")
    result = CatalogResult(
        dataframe=pd.DataFrame([{
            "warehouse_name": "Supplier",
            "item_name": "Panadol Extra 500mg Tablet",
            "base_price": 100.0,
            "discount_rate": 0.2,
            "stock_status": True,
        }]),
        diagnostics=ImportDiagnostics(unique_records=1, errors=["One region could not be verified"]),
        fingerprint=FileFingerprint.from_path(str(catalog)),
    )
    args = dict(
        order_files=[str(order)], catalog_files=[str(catalog)],
        output_dir=str(tmp_path / "reports"), catalog_cache={str(catalog): result},
    )
    with pytest.raises(PipelineExecutionError, match="Explicit acknowledgment"):
        run_procurement_pipeline(**args)

    approved = {result.acknowledgment_token}
    report = run_procurement_pipeline(**args, accepted_partial_tokens=approved)
    assert report["kpis"]["matched_items"] == 1

    catalog.write_text("Item Name,Public Price,Discount\nPanadol Extra 500mg Tablet,100,30%\n")
    with pytest.raises(PipelineExecutionError, match="changed after inspection"):
        run_procurement_pipeline(**args, accepted_partial_tokens=approved)
