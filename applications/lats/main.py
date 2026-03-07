"""
LATS (Language Agent Tree Search) – HumanEval on MASFactory.
Standard entry point: parse args, load dataset, build graph, run problems, tee to log.
Reference: https://arxiv.org/abs/2310.04406 and LanguageAgentTreeSearch-main/programming.
"""
import os
import sys
import json
import argparse

# Ensure repo root (parent of lats/) is on path so "lats" package resolves when run from lats/ or repo root
_APP_ROOT = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_APP_ROOT)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lats.humaneval.load import load_humaneval_jsonl, parse_internal_tests_from_test
from lats.humaneval.executor import verify_evaluation
from lats.workflows.graph import (
    build_graph,
    run_one_problem,
    LATS_MAX_ITERS,
    NUMBER_OF_TESTS,
)
from lats.utils.tee import tee, set_log_file, get_log_file
from lats.components.agents import set_print_code_attempts


def _default_dataset_path() -> str:
    p = os.path.join(_APP_ROOT, "assets", "config", "defaults.json")
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d.get("dataset_path"):
                    return d["dataset_path"]
        except Exception:
            pass
    return ""


def main():
    parser = argparse.ArgumentParser(
        description="LATS (Language Agent Tree Search) on HumanEval via MASFactory."
    )
    parser.add_argument(
        "--dataset",
        default="",
        help="HumanEval path: .jsonl or .jsonl.gz",
    )
    parser.add_argument("--max_iters", type=int, default=LATS_MAX_ITERS)
    parser.add_argument("--number_of_tests", type=int, default=NUMBER_OF_TESTS)
    parser.add_argument("--limit", type=int, default=0, help="Limit number of problems (0 = all)")
    parser.add_argument(
        "--print-code",
        action="store_true",
        help="Print each generated attempt (default: final solution only)",
    )
    parser.add_argument(
        "--log",
        type=str,
        default="",
        help="Append same output to file (e.g. logs/lats.log)",
    )
    args = parser.parse_args()

    set_print_code_attempts(args.print_code)
    log_file = None
    if args.log:
        try:
            os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
            log_file = open(args.log, "a", encoding="utf-8")
            set_log_file(log_file)
        except Exception as e:
            print(f"Warning: could not open log file {args.log}: {e}", flush=True)

    max_iters = args.max_iters
    number_of_tests = args.number_of_tests
    dataset_path = args.dataset or _default_dataset_path()
    if not dataset_path:
        dataset_path = os.path.join(
            os.path.dirname(_APP_ROOT),
            "1",
            "LanguageAgentTreeSearch-main",
            "programming",
            "benchmarks",
            "humaneval-py.jsonl",
        )

    dataset = load_humaneval_jsonl(dataset_path)
    if args.limit > 0:
        dataset = dataset[: args.limit]

    tee(f"Dataset: {dataset_path}", log_file)
    tee(f"Loaded {len(dataset)} problems. max_iters={max_iters}, number_of_tests={number_of_tests}", log_file)
    model_name = os.environ.get("LATS_MODEL", "gpt-4")
    tee(f"Model: {model_name}", log_file)

    if dataset:
        verify_evaluation({
            "entry_point": dataset[0].get("entry_point", ""),
            "test": dataset[0].get("test", ""),
            "prompt": dataset[0].get("prompt", ""),
        })

    g = build_graph()

    _vis_port = os.environ.get("MASFACTORY_VISUALIZER_PORT", "")
    _vis_host = os.environ.get("MASFACTORY_VISUALIZER_HOST", "127.0.0.1")
    try:
        import masfactory.visualizer as _vis
        _connected_bridge = _vis.connect_bridge(timeout_s=5.0)
        if _connected_bridge is not None:
            _connected_bridge.attach_graph(g)
            _vis.get_bridge = lambda: _connected_bridge
            print("Visualizer connected: runtime view enabled.")
        elif _vis_port:
            print("Visualizer: connection failed (runtime view disabled).")
            print(f"  Tried {_vis_host}:{_vis_port} — ensure MASFactory extension is open and listening on this port.")
    except Exception as e:
        if _vis_port:
            print("Visualizer connect error:", e)

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("Error: OPENAI_API_KEY is not set. Set it first, e.g.:")
        print("  set OPENAI_API_KEY=sk-your-key   (Windows)")
        print("  export OPENAI_API_KEY=sk-your-key   (Linux/Mac)")
        print("Get a key: https://platform.openai.com/account/api-keys")
        sys.exit(1)
    print("Using OPENAI_API_KEY from env. (401 = invalid key; check/regenerate at https://platform.openai.com/account/api-keys)")
    if not _vis_port:
        print("Tip: set MASFACTORY_VISUALIZER_PORT to enable the visualizer runtime view.")

    num_success = 0
    for idx, item in enumerate(dataset):
        problem = {
            "name": item.get("name", item.get("task_id", "")),
            "prompt": item.get("prompt", ""),
            "entry_point": item.get("entry_point", ""),
            "test": item.get("test", ""),
        }
        internal_tests = parse_internal_tests_from_test(
            problem["test"], max_tests=number_of_tests
        )
        try:
            best_code, passed = run_one_problem(
                problem, g, internal_tests, max_iters, number_of_tests
            )
        except Exception as e:
            best_code, passed = "", False
            err_msg = str(e).split("\n")[0][:80]
            tee(f"Warning: problem {idx+1} failed ({err_msg}), treating as not passed.", log_file)
        if passed:
            num_success += 1
        acc = round(num_success / (idx + 1), 2)
        tee(f"completed {idx+1}/{len(dataset)}: acc = {acc}", log_file)
        pname = problem.get("name", item.get("task_id", f"problem_{idx+1}"))
        tee(f"\n--------------------- FINAL SOLUTION [{pname}] passed={bool(passed)} ---------------------", log_file)
        tee(best_code if best_code else "(none)", log_file)
        tee("------------------------------------------\n", log_file)
        item["solution"] = best_code
        item["is_solved"] = passed
        item["acc"] = acc

    tee(f"Done. Pass@1 acc = {num_success}/{len(dataset)} = {round(num_success/len(dataset), 2)}", log_file)
    if log_file is not None:
        try:
            log_file.close()
        except Exception:
            pass
        set_log_file(None)


if __name__ == "__main__":
    main()
