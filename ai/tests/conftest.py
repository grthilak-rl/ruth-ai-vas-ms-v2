"""
Pytest configuration for unified runtime tests
"""

import pytest
import sys
from pathlib import Path

# Add ai directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture(scope="session")
def models_root():
    """Provide path to models directory."""
    return Path(__file__).parent.parent / "models"


@pytest.fixture(scope="session")
def test_data_dir():
    """Provide path to test data directory."""
    test_dir = Path(__file__).parent / "test_data"
    test_dir.mkdir(exist_ok=True)
    return test_dir
