# Good and Bad Tests

Examples use `pytest`, matching this repo.

## Good Tests

**Integration-style**: Test through real interfaces, not mocks of internal parts.

```python
# GOOD: Tests observable behavior through the public function
def test_rieder_sequence_yields_sentinel_unit_and_discounted_purchase(tmp_path):
    result = _sample_result(tmp_path / "position.png")
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["apply_pricing_adjustments"] = True

    payload = build_vendoc_payload(result)

    assert payload["positions"][0]["unit_price"] == 999999.0
    assert payload["positions"][0]["purchase_price"] == 31.33
```

Characteristics:

- Tests behavior callers care about (the exported payload)
- Uses the public API only (`build_vendoc_payload`)
- Survives internal refactors of the pricing helpers
- Describes WHAT, not HOW
- One logical assertion per concept

## Bad Tests

**Implementation-detail tests**: Coupled to internal structure.

```python
# BAD: Tests a private helper and its call shape
def test_apply_rieder_pricing_operations_called(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "vendoc_exporter._apply_rieder_pricing_operations",
        lambda v, m: calls.append((v, m)) or v,
    )
    build_vendoc_payload(_sample_result(...))
    assert calls  # breaks the moment the internal wiring changes
```

Red flags:

- Mocking internal collaborators (`_apply_rieder_pricing_operations` is ours)
- Testing private helpers directly when a public path exists
- Asserting on call counts/order
- Test breaks when refactoring without behavior change
- Test name describes HOW not WHAT

```python
# BAD: Bypasses the interface to verify against the DB directly
def test_export_writes_documents_row(db_conn):
    build_export_content(_sample_result(), "sql")
    row = db_conn.execute("SELECT * FROM documents WHERE id = 33").fetchone()
    assert row is not None

# GOOD: Verifies the generated artifact through the public function
def test_sql_export_includes_document_approval_columns():
    _ext, _media_type, content = build_export_content(_sample_result(), "sql")
    assert "approval_status" in content
    assert "'approved'" in content
```

<!-- Adapted from github.com/mattpocock/skills (MIT). -->
