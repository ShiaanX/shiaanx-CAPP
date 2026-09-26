"""Readers for MFCAD++ hierarchical HDF5 graph tensors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import h5py
import numpy as np


RELATION_DATASETS = ("E_1", "E_2", "E_3")


@dataclass(frozen=True)
class H5GraphBatch:
    """One graph batch from the MFCAD++ hierarchical HDF5 files."""

    name: str
    node_features: np.ndarray
    labels: np.ndarray
    edge_indices: tuple[np.ndarray, ...]
    edge_values: tuple[np.ndarray, ...]
    facet_features: np.ndarray
    facet_edge_index: np.ndarray
    facet_edge_values: np.ndarray
    facet_to_face_index: np.ndarray
    facet_to_face_values: np.ndarray
    cad_models: tuple[str, ...]

    @property
    def num_faces(self) -> int:
        return int(self.node_features.shape[0])

    @property
    def num_facets(self) -> int:
        return int(self.facet_features.shape[0])


def h5_split_path(dataset_root: str | Path, split: str) -> Path:
    """Return the HDF5 file path for a dataset split."""
    root = Path(dataset_root)
    filenames = {
        "train": "training_MFCAD++.h5",
        "training": "training_MFCAD++.h5",
        "val": "val_MFCAD++.h5",
        "validation": "val_MFCAD++.h5",
        "test": "test_MFCAD++.h5",
    }
    try:
        filename = filenames[split]
    except KeyError as exc:
        raise ValueError(f"Unsupported split: {split}") from exc
    return root / "hierarchical_graphs" / filename


def h5_group_names(path: str | Path, *, limit: int | None = None) -> list[str]:
    """List graph group names in numeric order."""
    with h5py.File(path, "r") as handle:
        names = sorted(handle.keys(), key=lambda value: int(value) if value.isdigit() else value)
    return names[:limit] if limit is not None else names


def iter_h5_graph_batches(path: str | Path, *, limit: int | None = None) -> Iterator[H5GraphBatch]:
    """Yield graph batches from a split file."""
    group_names = h5_group_names(path, limit=limit)
    with h5py.File(path, "r") as handle:
        for name in group_names:
            yield read_h5_graph_batch(handle, name)


def read_h5_graph_batch(handle: h5py.File, group_name: str) -> H5GraphBatch:
    """Read one HDF5 graph group."""
    group = handle[group_name]
    edge_indices: list[np.ndarray] = []
    edge_values: list[np.ndarray] = []
    for prefix in RELATION_DATASETS:
        edge_indices.append(group[f"{prefix}_idx"][()].astype(np.int64, copy=False))
        edge_values.append(group[f"{prefix}_values"][()].astype(np.float32, copy=False))

    return H5GraphBatch(
        name=group_name,
        node_features=group["V_1"][()].astype(np.float32, copy=False),
        labels=group["labels"][()].astype(np.int64, copy=False),
        edge_indices=tuple(edge_indices),
        edge_values=tuple(edge_values),
        facet_features=group["V_2"][()].astype(np.float32, copy=False),
        facet_edge_index=group["A_2_idx"][()].astype(np.int64, copy=False),
        facet_edge_values=group["A_2_values"][()].astype(np.float32, copy=False),
        facet_to_face_index=group["A_3_idx"][()].astype(np.int64, copy=False),
        facet_to_face_values=group["A_3_values"][()].astype(np.float32, copy=False),
        cad_models=tuple(value.decode("utf-8") for value in group["CAD_model"][()]),
    )


def scan_label_counts(path: str | Path, *, num_classes: int = 25, limit: int | None = None) -> np.ndarray:
    """Count class labels across a split."""
    counts = np.zeros(num_classes, dtype=np.int64)
    for batch in iter_h5_graph_batches(path, limit=limit):
        counts += np.bincount(batch.labels, minlength=num_classes)[:num_classes]
    return counts


def h5_file_summary(path: str | Path, *, limit: int | None = None, num_classes: int = 25) -> dict[str, object]:
    """Return split-level graph statistics."""
    group_count = 0
    model_count = 0
    face_count = 0
    facet_count = 0
    edge_counts = [0, 0, 0]
    facet_edge_count = 0
    incidence_count = 0
    label_counts = np.zeros(num_classes, dtype=np.int64)

    for batch in iter_h5_graph_batches(path, limit=limit):
        group_count += 1
        model_count += len(batch.cad_models)
        face_count += batch.num_faces
        facet_count += batch.num_facets
        facet_edge_count += int(batch.facet_edge_index.shape[0])
        incidence_count += int(batch.facet_to_face_index.shape[0])
        for index, edges in enumerate(batch.edge_indices):
            edge_counts[index] += int(edges.shape[0])
        label_counts += np.bincount(batch.labels, minlength=num_classes)[:num_classes]

    return {
        "path": str(path),
        "groups": group_count,
        "cad_models": model_count,
        "faces": face_count,
        "facets": facet_count,
        "edge_counts": {
            "convex_E_1": edge_counts[0],
            "concave_E_2": edge_counts[1],
            "smooth_E_3": edge_counts[2],
            "facet_A_2": facet_edge_count,
            "facet_to_face_A_3": incidence_count,
        },
        "label_counts": {str(index): int(count) for index, count in enumerate(label_counts)},
    }

