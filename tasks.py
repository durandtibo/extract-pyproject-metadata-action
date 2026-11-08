r"""Define the tasks that are executed with invoke."""

from __future__ import annotations

from invoke_tasklib import make_ns

__all__ = ["ns"]

# The action has no documentation, release or benchmarks.
ns = make_ns(exclude=["doc", "release", "test.benchmark"])
