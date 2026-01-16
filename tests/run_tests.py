#!/usr/bin/env python3
"""
VAS-MS-V2 Integration Test Runner

Usage:
    python run_tests.py                     # Run all tests
    python run_tests.py --auth              # Run only auth tests
    python run_tests.py --quick             # Run quick tests (no slow/requires_stream)
    python run_tests.py --report            # Generate HTML report
    python run_tests.py -k "test_auth"      # Run tests matching pattern
"""

import os
import sys
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# Add tests directory to path
TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR))


def print_banner():
    """Print test banner"""
    print("=" * 70)
    print("VAS-MS-V2 INTEGRATION TEST SUITE")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Base URL: {os.getenv('VAS_BASE_URL', 'http://10.30.250.245')}")
    print(f"Client ID: {os.getenv('VAS_DEFAULT_CLIENT_ID', 'vas-portal')}")
    print("=" * 70)
    print()


def check_dependencies():
    """Check if required dependencies are installed"""
    required = ["pytest", "httpx", "pydantic"]
    missing = []

    for package in required:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)

    if missing:
        print(f"ERROR: Missing required packages: {', '.join(missing)}")
        print(f"Run: pip install -r {TESTS_DIR}/requirements.txt")
        return False
    return True


def run_tests(args):
    """Run pytest with specified arguments"""
    pytest_args = [
        sys.executable, "-m", "pytest",
        str(TESTS_DIR / "integration"),
        "-v",
        "--tb=short",
    ]

    # Add marker filters
    if args.auth:
        pytest_args.extend(["-m", "auth"])
    elif args.device:
        pytest_args.extend(["-m", "device"])
    elif args.stream:
        pytest_args.extend(["-m", "stream"])
    elif args.consumer:
        pytest_args.extend(["-m", "consumer"])
    elif args.snapshot:
        pytest_args.extend(["-m", "snapshot"])
    elif args.bookmark:
        pytest_args.extend(["-m", "bookmark"])
    elif args.hls:
        pytest_args.extend(["-m", "hls"])
    elif args.quick:
        pytest_args.extend(["-m", "not slow and not requires_stream"])

    # Add pattern filter
    if args.k:
        pytest_args.extend(["-k", args.k])

    # Add HTML report
    if args.report:
        report_path = TESTS_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        pytest_args.extend(["--html", str(report_path), "--self-contained-html"])
        print(f"Report will be saved to: {report_path}")

    # Add parallel execution
    if args.parallel:
        pytest_args.extend(["-n", str(args.parallel)])

    # Add verbosity
    if args.verbose:
        pytest_args.append("-vv")

    # Add stop on first failure
    if args.failfast:
        pytest_args.append("-x")

    print(f"Running: {' '.join(pytest_args)}")
    print()

    return subprocess.run(pytest_args).returncode


def main():
    parser = argparse.ArgumentParser(description="VAS-MS-V2 Integration Test Runner")

    # Test category filters
    category_group = parser.add_mutually_exclusive_group()
    category_group.add_argument("--auth", action="store_true", help="Run only authentication tests")
    category_group.add_argument("--device", action="store_true", help="Run only device tests")
    category_group.add_argument("--stream", action="store_true", help="Run only stream tests")
    category_group.add_argument("--consumer", action="store_true", help="Run only consumer tests")
    category_group.add_argument("--snapshot", action="store_true", help="Run only snapshot tests")
    category_group.add_argument("--bookmark", action="store_true", help="Run only bookmark tests")
    category_group.add_argument("--hls", action="store_true", help="Run only HLS tests")
    category_group.add_argument("--quick", action="store_true", help="Run quick tests only (no slow/stream tests)")

    # Other options
    parser.add_argument("-k", type=str, help="Run tests matching pattern")
    parser.add_argument("--report", action="store_true", help="Generate HTML report")
    parser.add_argument("--parallel", "-n", type=int, help="Run tests in parallel (requires pytest-xdist)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Extra verbose output")
    parser.add_argument("--failfast", "-x", action="store_true", help="Stop on first failure")

    args = parser.parse_args()

    print_banner()

    if not check_dependencies():
        sys.exit(1)

    sys.exit(run_tests(args))


if __name__ == "__main__":
    main()
