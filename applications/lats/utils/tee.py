"""
Tee output to terminal and optional log file.
Used by main to duplicate progress/solutions to --log file.
"""
import sys
from typing import Optional, TextIO

_lats_log_file: Optional[TextIO] = None


def set_log_file(f: Optional[TextIO]) -> None:
    global _lats_log_file
    _lats_log_file = f


def get_log_file() -> Optional[TextIO]:
    return _lats_log_file


def tee(s: str, log_file: Optional[TextIO] = None) -> None:
    """Print to stdout and append to log_file (or global _lats_log_file) if set."""
    print(s, flush=True)
    f = log_file if log_file is not None else _lats_log_file
    if f is not None:
        try:
            f.write(s.rstrip() + "\n")
            f.flush()
        except Exception:
            pass
