"""Shared pytest fixtures. pytest loads this file automatically."""

import pytest


@pytest.fixture
def anyio_backend():
    # anyio's pytest plugin runs `@pytest.mark.anyio` tests on this event loop.
    return "asyncio"
