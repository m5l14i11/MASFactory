"""
LATS agents: base, LLM, Reflection (and Executor implemented as ReflectionAgent with role=executor).
"""
import os
from masfactory import Agent, OpenAIModel
from masfactory.core.message import ParagraphMessageFormatter

from . import formatters as fmt
from .tree import LATSNode
from ..humaneval.load import extract_python_code, parse_internal_tests_from_test
from ..humaneval.executor import run_internal_tests, full_evaluate
from ..utils.tee import tee, get_log_file

# Model instance (injected or from env)
model_instance = OpenAIModel(
    api_key=os.environ.get("OPENAI_API_KEY", ""),
    base_url=os.environ.get("OPENAI_API_BASE", ""),
    model_name=os.environ.get("LATS_MODEL", "gpt-4"),
)

# When True, print each attempt body to terminal and log (--print-code)
_print_code_attempts = False


def set_print_code_attempts(value: bool):
    global _print_code_attempts
    _print_code_attempts = value


_ENV_PUSH_KEYS = {
    "observation": "observation",
    "reward": "reward",
    "action": "action",
    "full_passed": "full_passed",
}


def _print_generated_func_body(func_body: str, problem_name: str = "") -> None:
    """Print generated code to terminal and log (if --log and --print-code)."""
    if not _print_code_attempts:
        return
    title = "GENERATED FUNC BODY"
    if problem_name:
        title += f" [{problem_name}]"
    tee(f"\n--------------------- {title} ---------------------", get_log_file())
    tee(func_body, get_log_file())
    tee("------------------------------------------\n", get_log_file())


def _run_humaneval_forward(input_dict: dict) -> dict:
    """HumanEval execution (originally HumanEvalEnvironment._forward). Used by ReflectionAgent with role=executor."""
    content = input_dict.get("action", "") or input_dict.get("content", "")
    raw = str(content).strip()
    problem = input_dict.get("problem") or {}
    internal_tests = input_dict.get("internal_tests") or []
    entry_point = problem.get("entry_point", "")
    test = problem.get("test", "")
    prompt = problem.get("prompt", "")

    fail_safe = {
        "observation": "Error: No valid Python code.",
        "reward": 0.0,
        "reward_internal": 0.0,
        "reward_real": 0.0,
        "full_passed": False,
        "action": raw,
        "problem": problem,
        "internal_tests": internal_tests,
    }

    code = extract_python_code(raw)
    if not code:
        fail_safe["observation"] = "Error: Use a ```python ... ``` block or full function."
        return fail_safe
    if "def " not in code and prompt:
        code = prompt.rstrip() + "\n" + code

    if _print_code_attempts:
        _print_generated_func_body(code, problem.get("name", ""))

    if not internal_tests:
        internal_tests = parse_internal_tests_from_test(test, max_tests=6)

    is_passing_internal, feedback, reward_internal = run_internal_tests(
        code, internal_tests, timeout=5
    )
    reward_real = 1.0 if full_evaluate(entry_point, code, test, timeout=10) else 0.0
    reward = reward_internal + reward_real

    return {
        "observation": feedback,
        "reward": reward,
        "reward_internal": reward_internal,
        "reward_real": reward_real,
        "full_passed": reward_real >= 1.0,
        "action": code,
        "problem": problem,
        "internal_tests": internal_tests,
    }


class LATSBaseAgent(Agent):
    """Base agent: config merged into kwargs; role can be used by subclasses (e.g. ReflectionAgent as executor)."""

    def __init__(self, name, *args, **kwargs):
        if args and isinstance(args[0], dict):
            kwargs = {**args[0], **kwargs}
            args = ()
        self._role = kwargs.pop("role", None)
        kwargs.setdefault("model", model_instance)
        super().__init__(name, *args, **kwargs)


class LATSLLMAgent(LATSBaseAgent):
    """Pass-through problem/internal_tests; formatter merges _lats_llm_passthrough to satisfy output_keys."""

    def step(self, input_dict: dict) -> dict:
        fmt._lats_llm_passthrough = {
            "problem": input_dict.get("problem"),
            "internal_tests": input_dict.get("internal_tests"),
        }
        return super().step(input_dict)

    def _forward(self, input_dict: dict) -> dict:
        out = super()._forward(input_dict)
        out["problem"] = input_dict.get("problem")
        out["internal_tests"] = input_dict.get("internal_tests")
        if "content" not in out or not str(out.get("content", "")).strip():
            out["content"] = (
                out.get("content")
                or out.get("action")
                or out.get("response")
                or out.get("text")
                or str(out)
            )
        return out


class ReflectionAgent(LATSBaseAgent):
    """Reflection node. When config role=executor, same class acts as Executor (HumanEval runner) for visualizer."""

    def __init__(self, name, *args, **kwargs):
        super().__init__(name, *args, **kwargs)
        if getattr(self, "_role", None) == "executor":
            self._push_keys = dict(_ENV_PUSH_KEYS)

    @property
    def push_keys(self):
        if getattr(self, "_role", None) == "executor":
            return dict(_ENV_PUSH_KEYS)
        return super().push_keys

    def step(self, input_dict: dict) -> dict:
        if getattr(self, "_role", None) != "executor":
            fmt._lats_reflection_passthrough = {
                k: input_dict.get(k)
                for k in (
                    "action",
                    "observation",
                    "reward",
                    "full_passed",
                    "problem",
                    "internal_tests",
                )
                if k in input_dict
            }
        return super().step(input_dict)

    def _forward(self, input_dict: dict) -> dict:
        if getattr(self, "_role", None) == "executor":
            ctx = None
            result = {}
            try:
                from masfactory.visualizer import get_bridge
                bridge = get_bridge() if get_bridge else None
                if bridge is not None:
                    ctx = bridge.node_start(self, input_dict)
            except Exception:
                pass
            try:
                result = _run_humaneval_forward(input_dict)
            finally:
                if ctx is not None:
                    try:
                        from masfactory.visualizer import get_bridge as _gb
                        b = _gb() if _gb else None
                        if b is not None:
                            b.node_end(ctx, result, node=self)
                    except Exception:
                        pass
            return result
        out = super()._forward(input_dict)
        ref = (out.get("content") or out.get("action") or str(out)).strip()
        out = {**out, "reflection": ref}
        out["problem"] = input_dict.get("problem")
        out["internal_tests"] = input_dict.get("internal_tests")
        out["action"] = input_dict.get("action")
        out["observation"] = input_dict.get("observation")
        out["reward"] = input_dict.get("reward")
        out["full_passed"] = input_dict.get("full_passed", False)
        return out
