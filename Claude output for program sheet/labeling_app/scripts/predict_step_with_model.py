#!/usr/bin/env python3
"""Run a trained HDF5 GNN checkpoint on OCP/ShiaanX STEP feature JSON."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

import torch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cad_feature_recognition_v2.labels import load_label_names  # noqa: E402
from cad_feature_recognition_v2.model import batch_to_torch, build_model  # noqa: E402
from cad_feature_recognition_v2.step_adapter import features_to_graph_batch, load_features_json  # noqa: E402


def choose_device(requested: str) -> torch.device:
    """Choose a supported inference device without importing training dependencies."""
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features_json", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--dataset", type=Path, default=Path("MFCAD++_dataset"))
    parser.add_argument("--clusters-json", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "outputs" / "step_model_predictions.json")
    parser.add_argument("--summary-out", type=Path)
    return parser.parse_args()


def topk_for_face(probs: torch.Tensor, label_names: dict[int, str], *, k: int = 3) -> list[dict[str, Any]]:
    values, indices = probs.topk(k)
    return [
        {
            "label_id": int(index),
            "label": label_names.get(int(index), str(int(index))),
            "probability": float(value),
        }
        for value, index in zip(values.cpu().tolist(), indices.cpu().tolist(), strict=True)
    ]


def majority_label(face_predictions: list[dict[str, Any]], face_indices: list[int]) -> dict[str, Any]:
    ids = [face_predictions[index]["label_id"] for index in face_indices if 0 <= index < len(face_predictions)]
    if not ids:
        return {"label_id": None, "votes": {}}
    counts = Counter(ids)
    label_id, count = counts.most_common(1)[0]
    return {
        "label_id": label_id,
        "vote_count": count,
        "vote_fraction": count / len(ids),
        "votes": {str(k): int(v) for k, v in sorted(counts.items())},
    }


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# STEP Model Prediction Summary",
        "",
        f"Features: `{payload['features_json']}`",
        f"Checkpoint: `{payload['checkpoint']}`",
        "",
        "This uses the trained HDF5 GNN through an OCP/ShiaanX JSON adapter. When available, the adapter uses real OCP mesh facets, facet adjacency, and directed B-Rep relation channels. It is still not a validated production STEP tensorizer because the model was trained on the MFCAD++ 25-class taxonomy, which does not include every production feature type.",
        "",
        "## Face Prediction Distribution",
        "",
        "| ID | Label | Faces | Mean probability |",
        "| ---: | --- | ---: | ---: |",
    ]
    for row in payload["label_distribution"]:
        lines.append(
            f"| {row['label_id']} | {row['label']} | {row['faces']} | {row['mean_probability']:.3f} |"
        )

    if payload.get("cluster_predictions"):
        lines.extend(
            [
                "",
                "## Cluster Majority Predictions",
                "",
                "| Cluster | Rule type | Model majority label | Vote fraction | Faces |",
                "| ---: | --- | --- | ---: | ---: |",
            ]
        )
        for cluster in payload["cluster_predictions"]:
            lines.append(
                f"| {cluster['cluster_id']} | {cluster.get('rule_feature_type', '-')} | "
                f"{cluster.get('model_label', '-')} | {cluster.get('vote_fraction', 0):.3f} | "
                f"{cluster.get('face_count', 0)} |"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    features_data = load_features_json(args.features_json)
    batch = features_to_graph_batch(features_data, name=args.features_json.stem)
    checkpoint = torch.load(args.checkpoint, map_location="cpu")
    config = checkpoint["config"]
    device = choose_device(args.device)
    label_names = load_label_names(args.dataset)

    model = build_model(
        model_arch=checkpoint.get("model_arch", config.get("model_arch", "hierarchical")),
        input_dim=checkpoint["input_dim"],
        hidden_dim=config["hidden_dim"],
        layers=config["layers"],
        dropout=config["dropout"],
    ).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    torch_batch = batch_to_torch(batch, device=device, surface_classes=config.get("surface_classes", 12))
    with torch.no_grad():
        logits = model(torch_batch)
        probs = torch.softmax(logits, dim=1)
        pred_ids = probs.argmax(dim=1)
        pred_conf = probs.max(dim=1).values

    faces = features_data["faces"]["faces"]
    face_predictions = []
    for index, (label_id, confidence) in enumerate(zip(pred_ids.cpu().tolist(), pred_conf.cpu().tolist(), strict=True)):
        face_predictions.append(
            {
                "face_index": index,
                "surface_type": faces[index].get("surface_type"),
                "area": faces[index].get("area"),
                "label_id": int(label_id),
                "label": label_names.get(int(label_id), str(int(label_id))),
                "probability": float(confidence),
                "top3": topk_for_face(probs[index], label_names, k=3),
            }
        )

    distribution = []
    for label_id, count in Counter(p["label_id"] for p in face_predictions).most_common():
        selected = [p["probability"] for p in face_predictions if p["label_id"] == label_id]
        distribution.append(
            {
                "label_id": int(label_id),
                "label": label_names.get(int(label_id), str(int(label_id))),
                "faces": int(count),
                "mean_probability": float(sum(selected) / len(selected)),
            }
        )

    cluster_predictions = []
    if args.clusters_json and args.clusters_json.exists():
        with args.clusters_json.open() as handle:
            cluster_data = json.load(handle)
        for cluster in cluster_data.get("clusters", []):
            face_indices = [int(i) for i in cluster.get("face_indices", [])]
            majority = majority_label(face_predictions, face_indices)
            label_id = majority.get("label_id")
            cluster_predictions.append(
                {
                    "cluster_id": cluster.get("cluster_id"),
                    "rule_feature_type": cluster.get("feature_type"),
                    "seed_type": cluster.get("seed_type"),
                    "face_count": len(face_indices),
                    "model_label_id": label_id,
                    "model_label": label_names.get(int(label_id), str(label_id)) if label_id is not None else None,
                    "vote_fraction": majority.get("vote_fraction", 0.0),
                    "votes": majority.get("votes", {}),
                    "face_indices": face_indices,
                }
            )

    mesh = features_data.get("mesh") or {}
    relation_count = len(features_data.get("face_edge_relations") or [])
    payload = {
        "features_json": str(args.features_json),
        "checkpoint": str(args.checkpoint),
        "adapter": {
            "node_features": "area/max_area, bbox-normalized centroid, MFCAD++ surface code",
            "edge_relations": (
                f"{relation_count} directed OCP face-edge relations"
                if relation_count
                else "fallback: same-surface/same-axis adjacency as smooth, other adjacency as convex/other"
            ),
            "mesh_level": (
                f"{mesh.get('total_facets')} OCP mesh facets"
                if mesh.get("total_facets")
                else "fallback: one pseudo facet per B-Rep face"
            ),
            "caveat": "model inference is real, but raw STEP accuracy is not validated and MFCAD++ does not cover every production feature class",
        },
        "face_count": len(face_predictions),
        "label_distribution": distribution,
        "face_predictions": face_predictions,
        "cluster_predictions": cluster_predictions,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    if args.summary_out:
        write_summary(args.summary_out, payload)
    print(json.dumps({"out": str(args.out), "summary_out": str(args.summary_out) if args.summary_out else None}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
