# When to Mock

Mock at **system boundaries** only:

- External APIs (the VenDoc MSSQL / `pyodbc` connection, email, etc.)
- Databases (sometimes — prefer a test DB or assert on the generated SQL script)
- Time/randomness (e.g. pass `exported_at` into `build_vendoc_payload` instead of reading the clock)
- File system (sometimes — the suite already writes real PNGs into `tmp_path`)

Don't mock:

- Your own modules/functions (`vendoc_exporter`, `exporter`, `parser`)
- Internal collaborators
- Anything you control

## Designing for Mockability

At system boundaries, design interfaces that are easy to mock.

**1. Use dependency injection**

Pass external dependencies in rather than creating them internally:

```python
# Easy to test: the config (boundary) is passed in
def write_srtemp_payload(vendoc_payload, config):
    with _connect(config) as conn:
        ...

# Hard to test: reaches out to the environment itself
def write_srtemp_payload(vendoc_payload):
    config = config_from_env()  # now the test must patch the environment
    ...
```

This repo already follows the good pattern — `write_srtemp_payload(payload, config)`
takes the connection config as an argument, and `build_srtemp_insert_script`
can run with no DB at all (it falls back to default column bindings).

**2. Prefer narrow, purpose-specific boundary functions**

Specific functions per external operation are easier to fake than one generic
gateway with conditional logic:

```python
# GOOD: each operation is independently fakeable
def list_customer_options(config, view_name=None): ...
def write_srtemp_payload(payload, config): ...

# BAD: one generic runner — tests must branch inside the fake
def run_mssql(operation, **kwargs): ...
```

`pytest`'s `monkeypatch` is the tool for the rare boundary fake — e.g. the suite
patches `vendoc_mssql._resolve_table_bindings` to test column-name resolution
without a live SQL Server.

<!-- Adapted from github.com/mattpocock/skills (MIT). -->
