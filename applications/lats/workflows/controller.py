"""
LATS controller: MCTS selection, expand, backprop, terminate. Uses tree set by graph before each invoke.
"""
from typing import Any, Optional

from ..components.tree import LATSNode, TreeManager, gather_context_from_tree

_lats_tree: Optional[TreeManager] = None


def set_lats_tree(tm: TreeManager | None) -> None:
    global _lats_tree
    _lats_tree = tm


def lats_controller_logic(message: dict, _attrs: Any) -> bool:
    """Return True to terminate loop; otherwise set reflexion_prompt and return False."""
    global _lats_tree
    if _lats_tree is None:
        message["final_code"] = ""
        message["final_passed"] = False
        return True

    action = message.get("action") or message.get("(not set yet)")
    if action == "(not set yet)":
        action = ""
    observation = message.get("observation", "")
    reward = message.get("reward", 0.0)
    try:
        reward = float(reward) if str(reward) != "(not set yet)" else 0.0
    except Exception:
        reward = 0.0
    full_passed = message.get("full_passed", False)
    if isinstance(full_passed, str) and "(not set yet)" in str(full_passed):
        full_passed = False
    full_passed = bool(full_passed)
    reflection = message.get("reflection", "")

    root = _lats_tree.root
    # First round: init root from first LLM output; else add child and backprop
    if action and action not in ("(not set yet)", "Empty", "Invalid_Instruction"):
        if not root.solution and root.visits == 0:
            root.solution = action
            root.test_feedback = observation
            root.reflection = reflection
            root.visits = 1
            root.value = reward
        else:
            selected = _lats_tree.current_node
            child = LATSNode(
                solution=action, parent=selected, depth=selected.depth + 1
            )
            child.test_feedback = observation
            child.reflection = reflection
            selected.children.append(child)
            _lats_tree.backprop(child, reward)

    if full_passed or root.visits >= _lats_tree._max_iters:
        best_node = root.best_child_value() if root.children else root
        best_code = (best_node.solution if best_node else "") or action or ""
        if full_passed and action:
            best_code = action
        message["final_code"] = best_code
        message["final_passed"] = full_passed
        return True

    selected = _lats_tree.selection()
    _lats_tree.current_node = selected
    path_impls, path_feedbacks, path_reflections = gather_context_from_tree(
        selected
    )

    # Build reflexion prompt (aligned with generator_utils.generate_with_accumulated_context)
    if not path_impls:
        reflexion_prompt = (
            "You are an AI that only responds with Python code. Write your full implementation (restate the function signature). "
            "Use a Python code block: ```python ... ```\n\n"
            + (_lats_tree.problem.get("prompt") or "")
        )
    else:
        parts = []
        for i, (impl, fb, ref) in enumerate(
            zip(path_impls, path_feedbacks, path_reflections)
        ):
            impl_short = impl[:2000] + "..." if len(impl) > 2000 else impl
            parts.append(
                f"[previous impl {i+1}]:\n```python\n{impl_short}\n```\n"
                f"[unit test results {i+1}]:\n{fb}\n[reflection {i+1}]:\n{ref}"
            )
        reflexion_prompt = (
            "You are an AI Python assistant. You will be given previous implementation(s), unit test results, and self-reflections. "
            "Write your full improved implementation (restate the function signature). Use only a ```python ... ``` block.\n\n"
            + "\n\n".join(parts)
            + "\n\n[improved impl]:\n"
            + (_lats_tree.problem.get("prompt") or "")
        )

    message["reflexion_prompt"] = reflexion_prompt
    message["action"] = "(not set yet)"
    message["observation"] = "(not set yet)"
    message["reward"] = 0.0
    message["reflection"] = ""
    return False
