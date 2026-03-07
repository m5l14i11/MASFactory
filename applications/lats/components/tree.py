"""
LATS search tree and MCTS: node, selection, backprop, context gathering.
"""
import math
from typing import List, Tuple


class LATSNode:
    def __init__(
        self,
        solution: str = "",
        parent: "LATSNode | None" = None,
        context: str = "",
        depth: int = 0,
    ):
        self.solution = solution
        self.parent = parent
        self.children: List[LATSNode] = []
        self.value = 0.0
        self.visits = 0
        self.context = context
        self.depth = depth
        self.reflection = ""
        self.test_feedback = ""

    def uct(self, exploration_weight: float = 1.0) -> float:
        if self.visits == 0:
            return self.value
        p = self.parent
        p_visits = p.visits if p else 1
        return (self.value / self.visits) + exploration_weight * math.sqrt(
            math.log(max(1, p_visits)) / self.visits
        )

    def best_child(self) -> "LATSNode | None":
        if not self.children:
            return None
        return max(self.children, key=lambda c: c.uct())

    def best_child_value(self) -> "LATSNode | None":
        if not self.children:
            return None
        return max(self.children, key=lambda c: c.value)

    def update(self, reward: float):
        self.visits += 1
        self.value += reward


def gather_context_from_tree(
    node: LATSNode,
) -> Tuple[List[str], List[str], List[str]]:
    """Collect (solution, test_feedback, reflection) from current node to root for reflexion context."""
    impls, feedbacks, reflections = [], [], []
    while node:
        if node.solution:
            impls.append(node.solution)
            feedbacks.append(node.test_feedback or "")
            reflections.append(node.reflection or "")
        node = node.parent
    return impls[::-1], feedbacks[::-1], reflections[::-1]


class TreeManager:
    def __init__(self, problem: dict, root: LATSNode):
        self.problem = problem
        self.root = root
        self.current_node = root
        self._max_iters = 8

    def selection(self) -> LATSNode:
        node = self.root
        while node.children:
            child = node.best_child()
            if child is None:
                break
            node = child
        return node

    def backprop(self, node: LATSNode, reward: float):
        temp = node
        while temp:
            temp.update(reward)
            temp = temp.parent
