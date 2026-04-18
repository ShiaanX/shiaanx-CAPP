"""
Pipeline observability: structured JSONL tracing for every stage decision.

Usage in each pipeline stage:
    from observability import PipelineTracer
    tracer = PipelineTracer.from_env()
    tracer.start_stage("classify_features", input_path="foo_clustered.json")
    tracer.decision("ddr_ratio", value=2.3, threshold=3.0, outcome="standard_cycle")
    tracer.metric("feature_type_distribution", {"through_hole": 4, "pocket": 2})
    tracer.warning("low confidence classification", {"cluster_id": 5, "type": "blind_hole"})
    tracer.end_stage(output_path="foo_classified.json", counts={"clusters": 12})

The runner sets PIPELINE_TRACE_FILE env var. If absent, a NoOpTracer is returned
and all calls silently discard — no behaviour change.
"""

import json
import os
import time
from pathlib import Path
from collections import defaultdict


class PipelineTracer:
    def __init__(self, trace_path: str):
        self.trace_path = trace_path
        self._stage_name: str | None = None
        self._stage_start: float | None = None
        Path(trace_path).parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Stage lifecycle
    # ------------------------------------------------------------------ #

    def start_stage(self, stage_name: str, input_path: str | None = None):
        self._stage_name = stage_name
        self._stage_start = time.time()
        self._write({
            "event": "stage_start",
            "stage": stage_name,
            "input": input_path,
        })

    def end_stage(self, output_path: str | None = None, counts: dict | None = None):
        elapsed_ms = round((time.time() - self._stage_start) * 1000) if self._stage_start else None
        self._write({
            "event": "stage_end",
            "stage": self._stage_name,
            "output": output_path,
            "elapsed_ms": elapsed_ms,
            "counts": counts or {},
        })

    # ------------------------------------------------------------------ #
    # Event types
    # ------------------------------------------------------------------ #

    def decision(
        self,
        signal: str,
        value=None,
        threshold=None,
        outcome: str | None = None,
        confidence: str | None = None,
        notes: str | None = None,
    ):
        self._write({
            "event": "decision",
            "stage": self._stage_name,
            "signal": signal,
            "value": value,
            "threshold": threshold,
            "outcome": outcome,
            "confidence": confidence,
            "notes": notes,
        })

    def metric(self, key: str, value):
        self._write({
            "event": "metric",
            "stage": self._stage_name,
            "key": key,
            "value": value,
        })

    def warning(self, message: str, context: dict | None = None):
        self._write({
            "event": "warning",
            "stage": self._stage_name,
            "message": message,
            "context": context or {},
        })

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _write(self, obj: dict):
        obj["ts"] = round(time.time(), 3)
        with open(self.trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, default=str) + "\n")

    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #

    @classmethod
    def from_env(cls) -> "PipelineTracer | _NoOpTracer":
        path = os.environ.get("PIPELINE_TRACE_FILE")
        if path:
            return cls(path)
        return _NoOpTracer()

    # ------------------------------------------------------------------ #
    # Summariser (called by runner after pipeline finishes)
    # ------------------------------------------------------------------ #

    @staticmethod
    def summarize(trace_path: str) -> dict:
        events = []
        try:
            with open(trace_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        except FileNotFoundError:
            return {}

        stages_ok, stages_fail = [], []
        warnings, decisions = [], []
        metrics: dict[str, dict] = {}
        stage_timings: dict[str, int] = {}

        for ev in events:
            evt = ev.get("event")
            stage = ev.get("stage", "")
            if evt == "stage_end":
                stage_timings[stage] = ev.get("elapsed_ms", 0)
                stages_ok.append(stage)
            elif evt == "warning":
                warnings.append(ev)
            elif evt == "decision":
                decisions.append(ev)
            elif evt == "metric":
                metrics.setdefault(stage, {})[ev["key"]] = ev["value"]

        # Roll up key counts
        feature_dist: dict = {}
        for stage, m in metrics.items():
            if "feature_type_distribution" in m:
                feature_dist = m["feature_type_distribution"]

        low_conf = sum(
            1 for d in decisions
            if d.get("confidence") == "low"
        )
        rpm_caps = sum(
            1 for w in warnings
            if "rpm" in w.get("message", "").lower() and "cap" in w.get("message", "").lower()
        )
        tool_subs = sum(
            1 for w in warnings
            if "substitut" in w.get("message", "").lower()
        )
        total_warnings = len(warnings)

        # Gather operation / cluster counts from stage_end counts
        total_clusters = 0
        total_ops = 0
        total_setups = 0
        for ev in events:
            if ev.get("event") == "stage_end":
                c = ev.get("counts", {})
                if "clusters" in c:
                    total_clusters = max(total_clusters, c["clusters"])
                if "operations" in c:
                    total_ops = max(total_ops, c["operations"])
                if "setups" in c:
                    total_setups = max(total_setups, c["setups"])

        return {
            "stages_completed": len(stages_ok),
            "stage_timings_ms": stage_timings,
            "total_clusters": total_clusters,
            "total_setups": total_setups,
            "total_operations": total_ops,
            "feature_distribution": feature_dist,
            "low_confidence_classifications": low_conf,
            "rpm_caps": rpm_caps,
            "tool_substitutions": tool_subs,
            "total_warnings": total_warnings,
        }


class _NoOpTracer:
    """Returned when PIPELINE_TRACE_FILE is not set. All calls are silent no-ops."""
    def start_stage(self, *a, **kw): pass
    def end_stage(self, *a, **kw): pass
    def decision(self, *a, **kw): pass
    def metric(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
