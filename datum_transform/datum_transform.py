"""
Datum Transform — Component 2
Reads features.json + <stepfile>.datums.json and writes features_datumed.json
with every feature's coordinates expressed in the datum reference frame.

Datum frame construction:
  Origin  = Datum A face centroid
  Z axis  = Datum A face normal (outward)
  X axis  = Datum B face normal projected onto the plane perpendicular to Z, normalised
  Y axis  = Z cross X  (right-hand rule)

Usage:
    python datum_transform/datum_transform.py <features.json> <stepfile.datums.json>

Writes: <features_basename>_datumed.json alongside the features file.
"""

import sys
import json
import math
import copy
from pathlib import Path


# ─── Vector helpers ────────────────────────────────────────────────────────────

def vec_sub(a, b):
    return [a[i] - b[i] for i in range(3)]

def vec_dot(a, b):
    return sum(a[i] * b[i] for i in range(3))

def vec_cross(a, b):
    return [
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    ]

def vec_norm(v):
    mag = math.sqrt(sum(x*x for x in v))
    if mag < 1e-12:
        raise ValueError(f"Cannot normalise zero vector: {v}")
    return [x / mag for x in v]

def vec_scale(v, s):
    return [x * s for x in v]

def vec_add(a, b):
    return [a[i] + b[i] for i in range(3)]

def project_onto_plane(v, plane_normal):
    """Remove the component of v along plane_normal."""
    n = vec_norm(plane_normal)
    d = vec_dot(v, n)
    return vec_sub(v, vec_scale(n, d))

def transform_point(p, origin, x_axis, y_axis, z_axis):
    """Express point p in the datum frame defined by origin + orthonormal axes."""
    rel = vec_sub(p, origin)
    return [
        round(vec_dot(rel, x_axis), 6),
        round(vec_dot(rel, y_axis), 6),
        round(vec_dot(rel, z_axis), 6),
    ]

def transform_direction(d, x_axis, y_axis, z_axis):
    """Rotate direction vector d into the datum frame (no translation)."""
    return [
        round(vec_dot(d, x_axis), 6),
        round(vec_dot(d, y_axis), 6),
        round(vec_dot(d, z_axis), 6),
    ]


# ─── Datum frame ───────────────────────────────────────────────────────────────

def build_datum_frame(datums):
    """
    Returns (origin, x_axis, y_axis, z_axis) from the tagged datum list.
    Raises ValueError if Datum A (and B for a full frame) are not present.
    """
    by_label = {d["label"]: d for d in datums}

    if "A" not in by_label:
        raise ValueError("Datum A is required to build the coordinate frame.")

    datum_a = by_label["A"]
    if not datum_a.get("normal"):
        raise ValueError("Datum A must be a planar face with a normal vector.")

    origin = datum_a["centroid"]
    z_axis = vec_norm(datum_a["normal"])

    if "B" in by_label and by_label["B"].get("normal"):
        b_normal = by_label["B"]["normal"]
        x_proj = project_onto_plane(b_normal, z_axis)
        if math.sqrt(sum(x*x for x in x_proj)) < 1e-9:
            print("[WARN] Datum B normal is parallel to Datum A normal — using fallback X axis")
            x_axis = _fallback_x(z_axis)
        else:
            x_axis = vec_norm(x_proj)
    else:
        print("[WARN] Datum B not found or not planar — using fallback X axis")
        x_axis = _fallback_x(z_axis)

    y_axis = vec_norm(vec_cross(z_axis, x_axis))

    # Reorthogonalise x in case of floating-point drift
    x_axis = vec_norm(vec_cross(y_axis, z_axis))

    return origin, x_axis, y_axis, z_axis


def _fallback_x(z_axis):
    """Choose an arbitrary X axis perpendicular to z_axis."""
    candidates = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for c in candidates:
        p = project_onto_plane(c, z_axis)
        if math.sqrt(sum(x*x for x in p)) > 0.1:
            return vec_norm(p)
    raise ValueError("Cannot find fallback X axis for the given Z axis.")


# ─── Feature coordinate transform ─────────────────────────────────────────────

def _transform_coords_dict(d, origin, xa, ya, za):
    """Transform a dict with x/y/z keys into datum frame."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d
    if "x" in d and "y" in d and "z" in d:
        pt = [d["x"], d["y"], d["z"]]
        t = transform_point(pt, origin, xa, ya, za)
        return {"x": t[0], "y": t[1], "z": t[2]}
    return d


def _transform_normal_dict(d, xa, ya, za):
    """Rotate a normal/direction dict into datum frame."""
    if d is None:
        return None
    if "x" in d and "y" in d and "z" in d:
        v = [d["x"], d["y"], d["z"]]
        t = transform_direction(v, xa, ya, za)
        return {"x": t[0], "y": t[1], "z": t[2]}
    return d


def transform_face(face, origin, xa, ya, za):
    """
    Deep-copy a face dict and add datum-frame coordinates.
    Preserves model-frame coords unchanged.
    """
    f = copy.deepcopy(face)

    # Plane
    if "plane" in f:
        pln = f["plane"]
        f["plane_datum"] = {
            "origin": _transform_coords_dict(pln.get("origin"), origin, xa, ya, za),
            "normal": _transform_normal_dict(pln.get("normal"), xa, ya, za),
        }

    # Cylinder
    if "cylinder" in f:
        cyl = f["cylinder"]
        f["cylinder_datum"] = {
            "radius": cyl.get("radius"),
            "axis_location": _transform_coords_dict(cyl.get("axis_location"), origin, xa, ya, za),
            "axis_direction": _transform_normal_dict(cyl.get("axis_direction"), xa, ya, za),
        }

    # Cone
    if "cone" in f:
        cone = f["cone"]
        f["cone_datum"] = {
            "semi_angle_deg": cone.get("semi_angle_deg"),
            "apex": _transform_coords_dict(cone.get("apex"), origin, xa, ya, za),
            "axis_direction": _transform_normal_dict(cone.get("axis_direction"), xa, ya, za),
        }

    # Sphere
    if "sphere" in f:
        sph = f["sphere"]
        f["sphere_datum"] = {
            "radius": sph.get("radius"),
            "center": _transform_coords_dict(sph.get("center"), origin, xa, ya, za),
        }

    return f


# ─── Cluster-level transform ───────────────────────────────────────────────────

def _transform_point_list(pts, origin, xa, ya, za):
    """Transform a list of [x,y,z] lists."""
    if not pts:
        return pts
    return [transform_point(p, origin, xa, ya, za) for p in pts]


def _maybe_transform_xyz(d, origin, xa, ya, za):
    if isinstance(d, dict) and "x" in d:
        return _transform_coords_dict(d, origin, xa, ya, za)
    return d


def transform_cluster(cluster, origin, xa, ya, za):
    c = copy.deepcopy(cluster)
    c["faces"] = [transform_face(f, origin, xa, ya, za) for f in c.get("faces", [])]
    return c


# ─── Which datum section does this cluster belong to? ─────────────────────────

def assign_datum_section(cluster_faces, datums):
    """
    Return the datum label of the tagged face if any face in the cluster is
    a datum face, otherwise 'GENERAL'.
    """
    face_indices = {f.get("face_index") for f in cluster_faces if "face_index" in f}
    for d in datums:
        if d["face_index"] in face_indices:
            return f"DATUM_{d['label']}"
    return "GENERAL"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: python datum_transform.py <features.json> <stepfile.datums.json>")
        sys.exit(1)

    features_path = Path(sys.argv[1])
    datums_path = Path(sys.argv[2])

    print(f"[*] Reading features:  {features_path}")
    print(f"[*] Reading datums:    {datums_path}")

    with open(features_path) as f:
        features = json.load(f)

    with open(datums_path) as f:
        datum_data = json.load(f)

    datums = datum_data.get("datums", [])
    if not datums:
        print("[ERROR] No datums in datums.json — tag at least Datum A first.")
        sys.exit(1)

    # Build coordinate frame
    origin, xa, ya, za = build_datum_frame(datums)
    print(f"[OK] Datum frame built:")
    print(f"     Origin  = {[round(v,3) for v in origin]}")
    print(f"     X axis  = {[round(v,3) for v in xa]}")
    print(f"     Y axis  = {[round(v,3) for v in ya]}")
    print(f"     Z axis  = {[round(v,3) for v in za]}")

    # Determine structure — features.json can be either the raw faces output
    # (from extract_features.py) or the clustered output (from cluster_features.py).
    output = copy.deepcopy(features)

    datum_frame_meta = {
        "origin_model_frame": origin,
        "x_axis": xa,
        "y_axis": ya,
        "z_axis": za,
        "datum_a_face_index": next((d["face_index"] for d in datums if d["label"] == "A"), None),
        "datum_b_face_index": next((d["face_index"] for d in datums if d["label"] == "B"), None),
        "datum_c_face_index": next((d["face_index"] for d in datums if d["label"] == "C"), None),
    }
    output["datum_frame"] = datum_frame_meta

    # Transform faces (raw features.json structure)
    if "faces" in output and isinstance(output["faces"], list):
        transformed_faces = []
        for face in output["faces"]:
            transformed_faces.append(transform_face(face, origin, xa, ya, za))
        output["faces"] = transformed_faces
        print(f"[OK] Transformed {len(transformed_faces)} faces")

    # Transform clusters (clustered features.json structure)
    if "clusters" in output and isinstance(output["clusters"], list):
        sections = {}
        for cluster in output["clusters"]:
            cluster_t = transform_cluster(cluster, origin, xa, ya, za)
            section = assign_datum_section(cluster.get("faces", []), datums)
            sections.setdefault(section, []).append(cluster_t)

        output["clusters"] = []
        for section_label in sorted(sections.keys()):
            for c in sections[section_label]:
                c["inspection_section"] = section_label
                output["clusters"].append(c)

        print(f"[OK] Transformed {len(output['clusters'])} clusters across {len(sections)} sections")

    # Write output
    out_path = features_path.parent / (features_path.stem + "_datumed.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[OK] Written: {out_path}")


if __name__ == "__main__":
    main()
