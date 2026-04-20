# CoCo v2 Test Suite

This directory contains comprehensive tests for CoCo v2, covering unit tests, integration tests, and fixtures.

## Test Organization

- **`conftest.py`** - Shared pytest fixtures and configuration
  - `mock_config` - Safe test configuration
  - `mock_statement_client` - Mocked SQL Statement Execution API
  - `mock_gateway_client` - Mocked Mosaic AI Gateway
  - `mock_lakebase` - In-memory Lakebase stub for session persistence
  - `mock_vector_search` - Mocked vector search client
  - `sample_patient_data` - 10 synthetic RWD patients

- **`unit/`** - Unit tests (no external dependencies, all mocked)
  - `test_config.py` - Config loading, env var interpolation, validation
  - `test_sql_statement_client.py` - Statement execution, polling, retries
  - `test_gateway_client.py` - LLM endpoint routing, retries, streaming
  - `test_guardrails.py` - SQL validation, read-only enforcement, schema checks
  - `test_signatures.py` - DSPy signature structure and field definitions
  - `test_data_generator.py` - Synthetic data generation, correlations, determinism
  - `test_tools.py` - Clinical codes, SQL generation, knowledge RAG, tool integration

- **`integration/`** - Integration tests (mocked Databricks services)
  - `test_responses_agent.py` - Agent end-to-end flow, streaming, trace IDs
  - `test_app_routes.py` - FastAPI routes, user isolation, error handling
  - `test_session_persistence.py` - Thread/message/run CRUD, state tracking

## Running Tests

### All tests
```bash
pytest
```

### Unit tests only
```bash
pytest -m unit
```

### Integration tests only
```bash
pytest -m integration
```

### Specific test file
```bash
pytest tests/unit/test_config.py
```

### Specific test class
```bash
pytest tests/unit/test_config.py::TestConfigLoading
```

### Specific test function
```bash
pytest tests/unit/test_config.py::TestConfigLoading::test_load_default_config
```

### With verbose output
```bash
pytest -v
```

### With short traceback format
```bash
pytest --tb=short
```

### Show print statements
```bash
pytest -s
```

### Stop on first failure
```bash
pytest -x
```

### Run only failing tests (requires pytest-last-failed plugin)
```bash
pytest --lf
```

## Test Markers

Tests are marked with markers to categorize them:

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.asyncio` - Async tests (use pytest-asyncio)

## Mocking Strategy

All tests use mocks to avoid real Databricks/database calls:

1. **Fixtures in `conftest.py`** provide pre-configured mocks
2. **AsyncMock** from `unittest.mock` for async APIs
3. **MagicMock** for synchronous APIs
4. **In-memory stubs** for Lakebase and data persistence

Example:
```python
@pytest.mark.unit
def test_something(mock_config: CocoConfig, mock_statement_client):
    # Use mocked dependencies
    client = SomeClient(config=mock_config, statement_client=mock_statement_client)
    # Test behavior without touching real databases
```

## Writing New Tests

1. **Choose unit or integration** based on whether external services are mocked or real
2. **Use fixtures** from `conftest.py` for common mocked dependencies
3. **Add marker** (`@pytest.mark.unit` or `@pytest.mark.integration`)
4. **Test behavior, not implementation** - focus on inputs/outputs, not internal details
5. **Avoid slow operations** - mock HTTP calls, database queries, file I/O
6. **Keep tests focused** - one test per behavior
7. **Use descriptive names** - `test_<what>_<when>_<expect>`

## Coverage

While tests don't need 100% coverage, focus on:
- Critical paths (user flows through agent and app)
- Error handling and edge cases
- Guardrails and security checks
- Configuration and initialization

Run with coverage:
```bash
pytest --cov=src/coco --cov-report=html
```

Then open `htmlcov/index.html` in a browser.

## Troubleshooting

### Import errors
```
ImportError: No module named 'coco'
```
Solution: Ensure you're running pytest from the repo root and `src/` is in `PYTHONPATH`:
```bash
export PYTHONPATH=/path/to/repo/src:$PYTHONPATH
pytest
```

### Fixture not found
```
fixture 'mock_config' not found
```
Solution: Ensure `conftest.py` is in the same directory or parent directory of test file.

### Async test failures
```
RuntimeError: Event loop is closed
```
Solution: Use `@pytest.mark.asyncio` on async test functions.

### Mock not being used
Ensure you're patching at the correct path:
```python
# Wrong: patch where it's defined
with patch("coco.config.get_config"):

# Right: patch where it's imported/used
with patch("coco.agent.guardrails.get_config"):
```

## CI/CD Integration

Tests are automatically run on:
- Pull requests (pytest all tests)
- Merge to main (pytest unit tests, then integration tests)
- Tag release (full test suite + coverage report)

See `.github/workflows/test.yml` for CI configuration.
