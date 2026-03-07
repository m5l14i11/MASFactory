"""
Load HumanEval dataset (.jsonl / .jsonl.gz) and parse internal tests from test string.
"""
import json
import gzip
import random
import re
from typing import List


def load_humaneval_jsonl(path: str) -> List[dict]:
    """Load HumanEval items from .jsonl or .jsonl.gz."""
    items = []
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
    else:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
    return items


def parse_internal_tests_from_test(test_str: str, max_tests: int = 6) -> List[str]:
    """Parse assert lines from HumanEval test string as internal tests (aligned with LATS number_of_tests)."""
    asserts = []
    for line in test_str.splitlines():
        line = line.strip()
        if line.startswith("assert candidate(") or (line.startswith("assert ") and "candidate(" in line):
            asserts.append(line)
    if not asserts:
        return asserts
    if len(asserts) > max_tests:
        asserts = random.sample(asserts, max_tests)
    return asserts


def extract_python_code(raw: str) -> str:
    """Extract Python code block or first complete function from LLM output."""
    raw = (raw or "").strip()
    code_match = re.search(r"```python\s*(.*?)\s*```", raw, re.DOTALL)
    if code_match:
        return code_match.group(1).strip()
    if "def " in raw:
        return raw
    return ""
