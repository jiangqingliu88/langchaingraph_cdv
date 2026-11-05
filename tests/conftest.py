"""Test configuration."""
import asyncio
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="function")
def event_loop():
    """Each test gets its own event loop — required for SQLAlchemy async + greenlet."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()
