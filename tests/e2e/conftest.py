"""pytest configuration for E2E tests (Direction A — Real A2A Integration Testing)."""

import os
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--server-url",
        default=os.environ.get("A2A_SERVER_URL", "http://localhost:8000"),
        help="A2A Test Server URL (default: http://localhost:8000)",
    )
    parser.addoption(
        "--concurrency",
        type=int,
        default=int(os.environ.get("E2E_CONCURRENCY", "5")),
        help="Number of concurrent tasks (default: 5)",
    )


@pytest.fixture(scope="session")
def server_url(request):
    return request.config.getoption("--server-url")


@pytest.fixture(scope="session")
def concurrency(request):
    return request.config.getoption("--concurrency")
