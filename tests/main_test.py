"""
Main Test Runner
================

Entry point for running all E2E tests.

Usage:
    uv run python tests/main_test.py              # Run all tests
    uv run python tests/main_test.py --verbose    # Verbose output
    uv run python tests/main_test.py -k "api"     # Filter by name

Or with pytest directly:
    uv run python -m pytest tests/main_test.py -v
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

# =============================================================================
# Import all test modules here
# =============================================================================
from tests.e2e.test_api_flow import *  # noqa: F401, F403
from tests.intent.test_intent_accuracy import *  # noqa: F401, F403

# Future test modules:
# from tests.e2e.test_concurrent import *  # noqa: F401, F403
# from tests.e2e.test_error_handling import *  # noqa: F401, F403
# from tests.unit.test_agents import *  # noqa: F401, F403


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    # Pass all CLI args to pytest
    args = sys.argv[1:] if len(sys.argv) > 1 else ["-v"]

    # Always add current file as test target
    args.insert(0, str(Path(__file__)))

    # Run pytest
    exit_code = pytest.main(args)
    sys.exit(exit_code)
