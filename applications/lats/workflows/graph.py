"""
LATS workflow: build RootGraph + Loop (LLM -> Executor -> Reflection -> controller), run_one_problem.
"""
import os
from typing import List, Tuple

from masfactory import RootGraph, NodeTemplate, Loop
from masfactory.core.message import ParagraphMessageFormatter

from ..components.formatters import ContentMessageFormatter
from ..components.agents import (
    LATSLLMAgent,
    ReflectionAgent,
    set_print_code_attempts,
)
from ..components.tree import LATSNode, TreeManager
from .controller import lats_controller_logic, set_lats_tree
from ..humaneval.executor import full_evaluate, verify_evaluation

# Paper/source run_lats_gpt4.sh: max_iters=8, number_of_tests=2
LATS_MAX_ITERS = int(os.environ.get("LATS_MAX_ITERS", "8"))
NUMBER_OF_TESTS = int(os.environ.get("NUMBER_OF_TESTS", "2"))

loop_nodes = [
    (
        "LLM_Agent",
        LATSLLMAgent,
        {
            "instructions": "You output ONLY Python code in a ```python ... ``` block. No explanations. Restate the function signature in your implementation.",
            "prompt_template": "{reflexion_prompt}",
            "formatters": [
                ParagraphMessageFormatter(),
                ContentMessageFormatter("content", merge_global="_lats_llm_passthrough"),
            ],
        },
    ),
    (
        "Executor",
        ReflectionAgent,
        {
            "role": "executor",
            "instructions": "Run HumanEval internal tests and full evaluation.",
            "pull_keys": {"problem": "problem", "internal_tests": "internal_tests", "content": "content"},
            "push_keys": {"observation": "observation", "reward": "reward", "action": "action", "full_passed": "full_passed"},
        },
    ),
    (
        "Reflection",
        ReflectionAgent,
        {
            "instructions": "You are a Python programming assistant. Given a function implementation and unit test results, write a few sentences explaining why the implementation is wrong. Do NOT output code, only the explanation.",
            "prompt_template": "[function impl]:\n```python\n{action}\n```\n\n[unit test results]:\n{observation}\n\n[self-reflection]:",
            "formatters": [
                ParagraphMessageFormatter(),
                ContentMessageFormatter("reflection", merge_global="_lats_reflection_passthrough"),
            ],
        },
    ),
]

LATSTemplate = NodeTemplate(
    Loop,
    max_iterations=LATS_MAX_ITERS,
    terminate_condition_function=lats_controller_logic,
    nodes=loop_nodes,
    edges=[
        ("controller", "LLM_Agent", {"reflexion_prompt": "reflexion_prompt", "problem": "problem", "internal_tests": "internal_tests"}),
        ("LLM_Agent", "Executor", {"content": "content", "problem": "problem", "internal_tests": "internal_tests"}),
        ("Executor", "Reflection", {"action": "action", "observation": "observation", "reward": "reward", "full_passed": "full_passed", "problem": "problem", "internal_tests": "internal_tests"}),
        ("Reflection", "controller", {"action": "action", "observation": "observation", "reward": "reward", "full_passed": "full_passed", "reflection": "reflection", "problem": "problem", "internal_tests": "internal_tests"}),
    ],
    pull_keys={"problem": "problem", "internal_tests": "internal_tests"},
    push_keys={"final_code": "final_code", "final_passed": "final_passed"},
)


def build_graph() -> RootGraph:
    """Build LATS RootGraph with single LATS node (Loop)."""
    g = RootGraph(
        name="LATS_Runner",
        nodes=[("LATS", LATSTemplate)],
        edges=[
            ("entry", "LATS", {"problem": "problem", "internal_tests": "internal_tests"}),
            ("LATS", "exit", {"final_code": "final_code", "final_passed": "final_passed"}),
        ],
    )
    g.build()
    # Wire Executor push_keys for visualizer
    try:
        lats_loop = getattr(g, "_nodes", {}).get("LATS")
        if lats_loop is not None and hasattr(lats_loop, "_nodes"):
            env_node = lats_loop._nodes.get("Executor")
            if env_node is not None and hasattr(env_node, "set_push_keys"):
                env_node.set_push_keys({
                    "observation": "observation",
                    "reward": "reward",
                    "action": "action",
                    "full_passed": "full_passed",
                })
    except Exception:
        pass
    return g


def run_one_problem(
    problem: dict,
    graph: RootGraph,
    internal_tests: List[str],
    max_iters: int,
    number_of_tests: int,
) -> Tuple[str, bool]:
    """Run LATS for one problem; return (best_solution, passed)."""
    set_lats_tree(None)
    prompt = problem.get("prompt", "")
    simple_prompt = (
        "You output ONLY Python code in a ```python ... ``` block. No explanations. "
        "Write your full implementation (restate the function signature).\n\n" + prompt
    )
    root = LATSNode(solution="", context=prompt)
    tm = TreeManager(problem, root)
    tm._max_iters = max_iters
    set_lats_tree(tm)

    initial_input = {
        "problem": problem,
        "internal_tests": internal_tests,
        "reflexion_prompt": simple_prompt,
    }
    result, _ = graph.invoke(initial_input)
    final_code = result.get("final_code", "") or ""
    final_passed = result.get("final_passed", False)
    if isinstance(final_passed, str) and "(not set yet)" in str(final_passed):
        final_passed = False
    final_passed = bool(final_passed)
    if not final_code and tm and tm.root:
        best_node = tm.root.best_child_value() if tm.root.children else tm.root
        if best_node and getattr(best_node, "solution", None):
            final_code = best_node.solution
        elif getattr(tm.root, "solution", None):
            final_code = tm.root.solution
        if final_code and not final_passed:
            final_passed = full_evaluate(
                tm.problem.get("entry_point", ""),
                final_code,
                tm.problem.get("test", ""),
                timeout=10,
            )
    set_lats_tree(None)
    return final_code, final_passed
