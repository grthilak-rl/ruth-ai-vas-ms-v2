"""
Broken Model Inference

Intentionally fails to test failure isolation.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Counter for controlled failure after N calls
_call_count = 0


def infer(frame: Any, **kwargs: Any) -> Dict[str, Any]:
    """
    Intentionally failing inference function.

    Always raises an exception to test failure isolation.
    """
    global _call_count
    _call_count += 1

    # Always fail - simulates a completely broken model
    raise RuntimeError(f"Intentional failure #{_call_count} for isolation testing")
