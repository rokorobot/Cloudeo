def pytest_configure(config):
    # Used by the V2C traceability matrix: a test showing that a prohibited
    # state or transition is rejected, not merely that a valid path works.
    config.addinivalue_line(
        "markers", "negative: rejects a prohibited state or transition (V2C traceability)"
    )
