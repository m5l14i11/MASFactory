# LATS (Language Agent Tree Search) – HumanEval on MASFactory

This directory is a [MASFactory](https://github.com/BUPT-GAMMA/MASFactory) application that reproduces **LATS** (Language Agent Tree Search) on the **HumanEval** (programming) benchmark.

- **Paper**: [Language Agent Tree Search Unifies Reasoning Acting and Planning in Language Models](https://arxiv.org/abs/2310.04406) (ICML 2024)
- **Upstream reference**: [LanguageAgentTreeSearch](https://github.com/andyz245/LanguageAgentTreeSearch) (programming / HumanEval)

## Layout

```
lats/
├── main.py                 # Entry: argparse, load dataset, build graph, run loop, tee to log
├── README.md
├── assets/
│   └── config/             # Config (default dataset path, etc.); datasets not in repo
│       └── defaults.json
├── workflows/              # Graph and controller
│   ├── graph.py            # Build RootGraph, LATSTemplate, run_one_problem
│   └── controller.py       # lats_controller_logic (MCTS select / expand / backprop / terminate)
├── components/             # Custom MASFactory components
│   ├── formatters.py       # ContentMessageFormatter, passthrough dicts
│   ├── agents.py           # LATSBaseAgent, LATSLLMAgent, ReflectionAgent, HumanEval executor
│   └── tree.py             # LATSNode, TreeManager, gather_context_from_tree
├── humaneval/              # HumanEval data and execution
│   ├── load.py             # load_humaneval_jsonl, parse_internal_tests_from_test, extract_python_code
│   ├── executor.py         # run_internal_tests, full_evaluate, verify_evaluation
│   └── timeout_utils.py    # function_with_timeout
└── utils/
    └── tee.py              # Tee output to terminal and optional log file
```

## Context and memory in this port

In the LATS paper and some references, **context** and **memory** appear as conceptual (or explicit) elements. In this MASFactory application we do **not** add separate **Context** or **Memory** nodes. They are implemented as follows.

### Context

**Role:** Provide the LLM with the accumulated trajectory (previous code attempts, test results, and reflections) so it can produce the next, improved attempt.

**Implementation:** Context is built **inside the controller** and passed to the LLM via the existing message flow:

1. After each **Reflection** step, the controller selects the next node (MCTS selection) and gets the path from that node back to the root.
2. `**gather_context_from_tree(selected)`** in `components/tree.py` collects along that path:
  - previous **solutions** (code),
  - **test_feedback** (unit test results),
  - **reflections** (short explanations of failure).
3. The controller assembles these into a single string `**reflexion_prompt`** (with blocks like `[previous impl 1]`, `[unit test results 1]`, `[reflection 1]`, etc.).
4. `**reflexion_prompt**` is passed to **LLM_Agent** as the prompt for the next iteration.

So “context” is **inlined into the prompt**: it is computed in `workflows/controller.py` and carried in the message key `reflexion_prompt` to the LLM node, without a dedicated Context node.

### Memory

**Role:** Persist the search tree (all tried solutions, feedback, rewards, and structure) across loop iterations.

**Implementation:** Memory is the **search tree** maintained by the controller:

1. `**LATSNode`** (in `components/tree.py`) stores per-node state: `solution`, `test_feedback`, `reflection`, `value`, `visits`, `parent`, `children`.
2. `**TreeManager**` holds the `root`, `current_node`, and `_max_iters`, and implements **selection** (UCT), **backprop** (reward update), and tree growth (adding children when the Executor returns a new attempt).
3. The controller **reads and updates** this tree each loop: it appends new children, runs backprop, and uses `gather_context_from_tree` to build the next context.

So “memory” is the **tree state** (nodes + manager) owned and updated by the controller logic; there is no separate Memory agent or node. The graph nodes you see in MASFactory are only: **LLM_Agent**, **Executor**, **Reflection**, and the **controller** (Loop’s terminate function). Context and memory are implemented **inside** the controller and the shared tree, not as extra nodes.

## Setup

From the repo root (parent of `lats/`):

```bash
# Install MASFactory and dependencies (openai, etc.)
pip install masfactory openai

# Optional: set default dataset in assets/config/defaults.json
# "dataset_path": "path/to/HumanEval.jsonl.gz"
```

Environment variables:

- **OPENAI_API_KEY** (required)
- **OPENAI_API_BASE** (optional, for proxy/custom endpoint)
- **LATS_MODEL** (optional, default `gpt-4`)
- **LATS_MAX_ITERS** (optional, default `8`)
- **NUMBER_OF_TESTS** (optional, default `2`)
- **MASFACTORY_VISUALIZER_PORT** (optional, for runtime view)

## Run

From the repo root (e.g. `D:\PE`):

```bash
# Default dataset path may be read from assets/config/defaults.json
python lats/main.py --dataset "path/to/HumanEval.jsonl.gz" --log logs/lats.log
```

Examples:

```bash
# Limit to 5 problems, write same output to log file
python lats/main.py --dataset "path/to/HumanEval.jsonl.gz" --limit 5 --log logs/lats.log

# Print every attempt (not only final solution)
python lats/main.py --dataset "path/to/HumanEval.jsonl.gz" --print-code --log logs/lats.log

# Paper-aligned defaults: max_iters=8, number_of_tests=2 (no need to pass if using env or defaults)
python lats/main.py --dataset "path/to/HumanEval.jsonl.gz" --log logs/lats.log
```

Output is printed to the terminal and, when `--log` is set, appended to the given file.

## Metrics

- **Pass@1**: fraction of problems for which the best solution passes the full HumanEval test.
- Defaults align with the upstream GPT-4 run script: `max_iters=8`, `number_of_tests=2`.

