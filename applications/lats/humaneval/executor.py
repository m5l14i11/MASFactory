"""
HumanEval executor: internal tests + full evaluate. Uses fresh globals per run to avoid cross-problem pollution.
"""
import re
from typing import List, Tuple

from .timeout_utils import function_with_timeout


def _fresh_globals():
    """Fresh namespace for each evaluation to avoid function name pollution between problems."""
    import builtins
    g = {"__builtins__": builtins}
    exec("from typing import *", g)
    return g


def run_internal_tests(
    func: str, tests: List[str], timeout: int = 5
) -> Tuple[bool, str, float]:
    """Run internal tests; return (all_passed, feedback_string, reward_internal = passed/total)."""
    success_tests = []
    failed_tests = []
    for test in tests:
        g = _fresh_globals()
        try:
            function_with_timeout(exec, (f"{func}\n{test}", g), timeout)
            success_tests.append(test)
        except Exception:
            out = get_test_output(func, test, timeout)
            failed_tests.append(f"{test} # output: {out}")
    feedback = "Tested passed:"
    for t in success_tests:
        feedback += f"\n{t}"
    feedback += "\n\nTests failed:"
    for t in failed_tests:
        feedback += f"\n{t}"
    n = len(tests)
    reward_internal = (len(success_tests) / n) if n else 0.0
    return (len(failed_tests) == 0, feedback, reward_internal)


def get_test_output(func: str, assert_statement: str, timeout: int) -> str:
    """Execute single assert and return actual output (for failure message)."""
    g = _fresh_globals()
    try:
        exec(func, g)
        s = re.sub(r"^assert\s+", "", assert_statement.strip()).split(" # ")[0].strip()
        if " == " in s:
            call_str = s.split(" == ")[0].strip()
        else:
            call_str = s
        return str(function_with_timeout(eval, (call_str, g), timeout))
    except TimeoutError:
        return "TIMEOUT"
    except Exception as e:
        return str(e)


def full_evaluate(entry_point: str, func: str, test: str, timeout: int = 10) -> bool:
    """Official HumanEval full evaluation: func + test + check(entry_point). Uses fresh namespace."""
    code = f"{func}\n\n{test}\n\ncheck({entry_point})"
    g = _fresh_globals()
    try:
        function_with_timeout(exec, (code, g), timeout)
        return True
    except Exception:
        return False


def verify_evaluation(problem: dict) -> None:
    """Startup check: wrong implementation must be rejected, else evaluation logic is buggy."""
    import sys
    entry_point = problem.get("entry_point", "")
    test = problem.get("test", "")
    if not entry_point or not test:
        return
    wrong_impl = f"def {entry_point}(*args, **kwargs):\n    return 0"
    if full_evaluate(entry_point, wrong_impl, test, timeout=5):
        print("ERROR: Evaluation bug: a wrong solution was marked as PASSED. Fix full_evaluate.")
        sys.exit(1)
    print("Evaluation verification passed (wrong solution correctly rejected).")
