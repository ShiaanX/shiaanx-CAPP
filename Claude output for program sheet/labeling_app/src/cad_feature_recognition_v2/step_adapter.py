"""Adapt OCP/ShiaanX STEP feature JSON into model inference graph batches."""

from __future__ import annotations

from pathlib import Path
import json
import math
from typing import Any

import numpy as np

from .h5_data import H5GraphBatch


SURFACE_CODE = {
    "Plane": 1,
    "Cylinder": 2,
    "Cone": 3,
    "Sphere": 4,
    "Torus": 5,
    "Bezier": 6,
    "BSpline": 7,
    "SurfaceOfRevolution": 8,
    "SurfaceOfExtrusion": 9,
    "Offset": 10,
    "Other": 11,
    "Unknown": 0,
}


def load_features_json(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open() as handle:
        return json.load(handle)


def _point_tuple(point: dict[str, Any] | None) -> tuple[float, float, float]:
    if not point:
        return 0.0, 0.0, 0.0
    return float(point.get("x", 0.0)), float(point.get("y", 0.0)), float(point.get("z", 0.0))


def _vec_norm(values: tuple[float, float, float]) -> tuple[float, float, float]:
    mag = math.sqrt(values[0] ** 2 + values[1] ** 2 + values[2] ** 2)
    if mag <= 1e-12:
        return 0.0, 0.0, 1.0
    return values[0] / mag, values[1] / mag, values[2] / mag


def face_centroid(face: dict[str, Any]) -> tuple[float, float, float]:
    """Return face centroid, falling back to analytic surface reference points."""
    if "centroid" in face:
        return _point_tuple(face["centroid"])
    surface = face.get("surface_type")
    if surface == "Plane":
        return _point_tuple(face.get("plane", {}).get("origin"))
    if surface == "Cylinder":
        return _point_tuple(face.get("cylinder", {}).get("axis_location"))
    if surface == "Cone":
        cone = face.get("cone", {})
        return _point_tuple(cone.get("apex") or cone.get("axis_location"))
    if surface == "Sphere":
        return _point_tuple(face.get("sphere", {}).get("center"))
    if surface == "Torus":
        return _point_tuple(face.get("torus", {}).get("center"))
    return 0.0, 0.0, 0.0


def face_normal_or_axis(face: dict[str, Any]) -> tuple[float, float, float]:
    """Return a stable normal-like vector for pseudo-facet features."""
    surface = face.get("surface_type")
    if surface == "Plane":
        return _vec_norm(_point_tuple(face.get("plane", {}).get("normal")))
    if surface == "Cylinder":
        return _vec_norm(_point_tuple(face.get("cylinder", {}).get("axis_direction")))
    if surface == "Cone":
        return _vec_norm(_point_tuple(face.get("cone", {}).get("axis_direction")))
    return 0.0, 0.0, 1.0


def _normal_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    a = face_normal_or_axis(left)
    b = face_normal_or_axis(right)
    return abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _edge_relation(left: dict[str, Any], right: dict[str, Any]) -> int:
    """Approximate MFCAD++ edge relation: 0 convex/other, 2 smooth.

    The OCP JSON currently does not carry signed dihedral angles, so concave vs
    convex is not recoverable here. Same-surface, same-axis/normal neighbours are
    treated as smooth; all other adjacency goes to the convex/other channel.
    """
    if left.get("surface_type") == right.get("surface_type") and _normal_similarity(left, right) > 0.98:
        return 2
    return 0


def _edge_arrays_from_json(features_data: dict[str, Any], faces: list[dict[str, Any]]) -> tuple[list[np.ndarray], list[np.ndarray]]:
    relation_edges: list[list[tuple[int, int]]] = [[], [], []]
    relation_map = {"convex": 0, "concave": 1, "smooth": 2}
    face_count = len(faces)

    explicit_relations = features_data.get("face_edge_relations") or []
    if explicit_relations:
        for item in explicit_relations:
            source = int(item.get("source", -1))
            target = int(item.get("target", -1))
            relation = relation_map.get(item.get("relation"), 0)
            if 0 <= source < face_count and 0 <= target < face_count:
                relation_edges[relation].append((source, target))
    else:
        adjacency = features_data.get("face_adjacency", {})
        for raw_left, neighbours in adjacency.items():
            left = int(raw_left)
            if left < 0 or left >= face_count:
                continue
            for right in neighbours:
                right = int(right)
                if right < 0 or right >= face_count:
                    continue
                rel = _edge_relation(faces[left], faces[right])
                relation_edges[rel].append((left, right))

    edge_indices = []
    edge_values = []
    for edges in relation_edges:
        if edges:
            edge_indices.append(np.array(edges, dtype=np.int64))
            edge_values.append(np.ones(len(edges), dtype=np.float32))
        else:
            edge_indices.append(np.zeros((0, 2), dtype=np.int64))
            edge_values.append(np.zeros((0,), dtype=np.float32))
    return edge_indices, edge_values


def _mesh_arrays_from_json(
    features_data: dict[str, Any],
    faces: list[dict[str, Any]],
    centroids: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mesh = features_data.get("mesh") or {}
    facets = mesh.get("facets") or []
    if facets:
        normals = []
        d_values = []
        incidence = []
        for facet_index, facet in enumerate(facets):
            normal = facet.get("normal", {})
            nx = float(normal.get("x", 0.0))
            ny = float(normal.get("y", 0.0))
            nz = float(normal.get("z", 1.0))
            normals.append([(nx + 1.0) * 0.5, (ny + 1.0) * 0.5, (nz + 1.0) * 0.5])
            d_values.append(float(facet.get("d", 0.0)))
            face_index = int(facet.get("face_index", 0))
            incidence.append((facet_index, face_index))
        facet_features = np.column_stack([np.array(normals, dtype=np.float32), np.array(d_values, dtype=np.float32)])

        adjacency = mesh.get("facet_adjacency", {})
        facet_edges = []
        for raw_source, neighbours in adjacency.items():
            source = int(raw_source)
            for target in neighbours:
                facet_edges.append((source, int(target)))
        if facet_edges:
            facet_edge_index = np.array(facet_edges, dtype=np.int64)
            facet_edge_values = np.ones(len(facet_edges), dtype=np.float32)
        else:
            facet_edge_index = np.array([(i, i) for i in range(len(facets))], dtype=np.int64)
            facet_edge_values = np.ones(len(facets), dtype=np.float32)
        facet_to_face_index = np.array(incidence, dtype=np.int64)
        facet_to_face_values = np.ones(len(incidence), dtype=np.float32)
        return facet_features, facet_edge_index, facet_edge_values, facet_to_face_index, facet_to_face_values

    normals = np.array([face_normal_or_axis(face) for face in faces], dtype=np.float32)
    normals_01 = (normals + 1.0) * 0.5
    d_coeff = -np.sum(normals * centroids, axis=1, dtype=np.float32)
    facet_features = np.column_stack([normals_01, d_coeff]).astype(np.float32)
    face_count = len(faces)
    facet_edge_index = np.array([(i, i) for i in range(face_count)], dtype=np.int64)
    facet_edge_values = np.ones(face_count, dtype=np.float32)
    facet_to_face_index = np.array([(i, i) for i in range(face_count)], dtype=np.int64)
    facet_to_face_values = np.ones(face_count, dtype=np.float32)
    return facet_features, facet_edge_index, facet_edge_values, facet_to_face_index, facet_to_face_values


def mesh_normal_consistency(features_data: dict[str, Any]) -> dict[int, float]:
    """Return per-face normal consistency from mesh facets.

    Values near 1.0 mean all facet normals on that face agree, which indicates
    the face behaves like a plane even if STEP imported it as a BSpline.
    """
    mesh = features_data.get("mesh") or {}
    facets = mesh.get("facets") or []
    face_to_facets = mesh.get("face_to_facets") or {}
    result: dict[int, float] = {}
    for raw_face, facet_ids in face_to_facets.items():
        sx = sy = sz = total = 0.0
        for facet_id in facet_ids:
            facet = facets[int(facet_id)]
            normal = facet.get("normal", {})
            area = float(facet.get("area", 1.0) or 1.0)
            sx += float(normal.get("x", 0.0)) * area
            sy += float(normal.get("y", 0.0)) * area
            sz += float(normal.get("z", 1.0)) * area
            total += area
        if total > 0:
            result[int(raw_face)] = math.sqrt(sx * sx + sy * sy + sz * sz) / total
    return result


def effective_surface_type(face: dict[str, Any], *, consistency: float | None) -> str:
    """Map STEP/OCP surface names to the model's training-time surface family."""
    surface = face.get("surface_type", "Unknown")
    if surface in {"BSpline", "Bezier", "Other", "Offset"} and consistency is not None and consistency > 0.985:
        return "Plane"
    return surface


def features_to_graph_batch(features_data: dict[str, Any], *, name: str = "step_part") -> H5GraphBatch:
    """Build an inference batch compatible with the trained HDF5 GNN."""
    faces = features_data["faces"]["faces"]
    face_count = len(faces)
    bbox = features_data.get("bounding_box", {})
    bb_min = np.array(
        [bbox.get("xmin", 0.0), bbox.get("ymin", 0.0), bbox.get("zmin", 0.0)],
        dtype=np.float32,
    )
    bb_size = np.array(
        [bbox.get("length_x", 1.0) or 1.0, bbox.get("length_y", 1.0) or 1.0, bbox.get("length_z", 1.0) or 1.0],
        dtype=np.float32,
    )

    areas_raw = np.array([float(face.get("area", 0.0)) for face in faces], dtype=np.float32)
    max_area = float(areas_raw.max()) if areas_raw.size and areas_raw.max() > 0 else 1.0
    centroids = np.array([face_centroid(face) for face in faces], dtype=np.float32)
    centroids_norm = (centroids - bb_min) / bb_size
    centroids_norm = np.nan_to_num(centroids_norm, nan=0.0, posinf=0.0, neginf=0.0)

    consistency_by_face = mesh_normal_consistency(features_data)
    surface = np.array(
        [
            SURFACE_CODE.get(effective_surface_type(face, consistency=consistency_by_face.get(index)), 0) / 11.0
            for index, face in enumerate(faces)
        ],
        dtype=np.float32,
    )
    node_features = np.column_stack([areas_raw / max_area, centroids_norm, surface]).astype(np.float32)

    edge_indices, edge_values = _edge_arrays_from_json(features_data, faces)
    (
        facet_features,
        facet_edge_index,
        facet_edge_values,
        facet_to_face_index,
        facet_to_face_values,
    ) = _mesh_arrays_from_json(features_data, faces, centroids)

    return H5GraphBatch(
        name=name,
        node_features=node_features,
        labels=np.zeros(face_count, dtype=np.int64),
        edge_indices=tuple(edge_indices),
        edge_values=tuple(edge_values),
        facet_features=facet_features,
        facet_edge_index=facet_edge_index,
        facet_edge_values=facet_edge_values,
        facet_to_face_index=facet_to_face_index,
        facet_to_face_values=facet_to_face_values,
        cad_models=(name,),
    )
