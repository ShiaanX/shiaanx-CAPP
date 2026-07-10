"""
Datum Tagger Server
Flask backend that tessellates a STEP file with PythonOCC, serves face-indexed
geometry to the browser, and saves datum tags to <stepfile>.datums.json.

Usage:
    conda run -n occ python datum_tagger/server.py <path/to/file.step>
    Then open http://localhost:5050 in a browser.
"""

import sys
import os
import json
import math
import hashlib
import datetime
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import topods
from OCC.Core.BRepGProp import brepgprop_SurfaceProperties
from OCC.Core.GProp import GProp_GProps

app = Flask(__name__, static_folder=os.path.dirname(__file__))

STEP_PATH = None
FACE_DATA = None   # cached tessellation result
FEATURES_DATUMED_PATH = None   # optional — for feature map view


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def tessellate_step(step_path, linear_deflection=0.05, angular_deflection=0.5):
    """
    Load STEP file with PythonOCC, tessellate every face, return list of
    per-face dicts with index, mesh vertices/triangles, surface type,
    normal (for planes), and centroid.

    Face index is the 0-based enumeration order from TopExp_Explorer(TopAbs_FACE),
    matching the order used by extract_features.py.
    """
    reader = STEPControl_Reader()
    status = reader.ReadFile(step_path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Failed to read STEP file: {step_path}")
    reader.TransferRoots()
    shape = reader.OneShape()

    # Mesh the whole shape once (faster than per-face)
    mesh = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection, True)
    mesh.Perform()

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    faces = []
    face_index = 0

    while explorer.More():
        face = topods.Face(explorer.Current())
        loc = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation(face, loc)

        verts = []
        tris = []

        if triangulation is not None and triangulation.NbNodes() > 0:
            trsf = loc.IsIdentity() or loc.Transformation()

            for i in range(1, triangulation.NbNodes() + 1):
                n = triangulation.Node(i)
                if not loc.IsIdentity():
                    n.Transform(loc.Transformation())
                verts.extend([round(n.X(), 6), round(n.Y(), 6), round(n.Z(), 6)])

            for i in range(1, triangulation.NbTriangles() + 1):
                t = triangulation.Triangle(i)
                n1, n2, n3 = t.Get()
                # 0-based indices
                tris.extend([n1 - 1, n2 - 1, n3 - 1])

        # Surface type and geometric info
        surf = BRepAdaptor_Surface(face, True)
        surf_type = surf.GetType()

        normal = None
        face_type_str = "other"

        if surf_type == GeomAbs_Plane:
            face_type_str = "plane"
            pln = surf.Plane()
            d = pln.Axis().Direction()
            normal = [round(d.X(), 6), round(d.Y(), 6), round(d.Z(), 6)]
            # Flip normal if face is reversed
            if face.Orientation() == 1:  # TopAbs_REVERSED
                normal = [-normal[0], -normal[1], -normal[2]]
        elif surf_type == GeomAbs_Cylinder:
            face_type_str = "cylinder"

        # Centroid
        props = GProp_GProps()
        brepgprop_SurfaceProperties(face, props)
        cog = props.CentreOfMass()
        centroid = [round(cog.X(), 6), round(cog.Y(), 6), round(cog.Z(), 6)]

        faces.append({
            "face_index": face_index,
            "face_type": face_type_str,
            "normal": normal,
            "centroid": centroid,
            "vertices": verts,
            "triangles": tris,
        })

        face_index += 1
        explorer.Next()

    return faces


@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "datum_tagger.html")


@app.route("/map")
def feature_map():
    return send_from_directory(os.path.dirname(__file__), "feature_map.html")


@app.route("/api/feature_map_data")
def get_feature_map_data():
    """
    Returns face geometry annotated with feature IDs from features_datumed.json.
    Each face entry gets: feature_id, feature_type, inspection_section, centroid_datum.
    If no datumed JSON is loaded, falls back to face index labelling.
    """
    global FACE_DATA, FEATURES_DATUMED_PATH

    if FACE_DATA is None:
        abort(503, "Model not loaded")

    # Build face_index -> feature annotation map
    annotations = {}  # face_index -> {feature_id, feature_type, inspection_section, centroid_datum}

    if FEATURES_DATUMED_PATH and Path(FEATURES_DATUMED_PATH).exists():
        with open(FEATURES_DATUMED_PATH) as f:
            datumed = json.load(f)

        clusters = datumed.get("clusters")
        if clusters:
            # Cluster-level features — assign feature ID to every face in cluster
            feature_counter = {}
            for cluster in clusters:
                ftype = cluster.get("feature_type") or cluster.get("type") or "feature"
                feature_counter[ftype] = feature_counter.get(ftype, 0) + 1
                prefix_map = {
                    "through_hole": "BORE", "blind_hole": "BORE", "tapped_hole": "TAP",
                    "counterbore": "CBORE", "countersink": "CSINK",
                    "pocket": "POCKET", "rectangular_pocket": "POCKET",
                    "boss": "BOSS", "slot": "SLOT", "chamfer": "CHAM",
                    "planar_face": "FACE", "large_bore": "BORE",
                }
                prefix = prefix_map.get(ftype.lower(), ftype[:4].upper())
                fid = cluster.get("cluster_id") or f"{prefix}_{feature_counter[ftype]:03d}"
                section = cluster.get("inspection_section", "GENERAL")
                for face in cluster.get("faces", []):
                    idx = face.get("face_index")
                    if idx is not None:
                        cd = None
                        if "plane_datum" in face and face["plane_datum"]:
                            o = face["plane_datum"].get("origin")
                            cd = [o["x"], o["y"], o["z"]] if o else None
                        annotations[idx] = {
                            "feature_id": fid,
                            "feature_type": ftype,
                            "inspection_section": section,
                            "centroid_datum": cd,
                        }
        else:
            # Raw face-level — use face index as feature ID
            raw_faces = datumed.get("faces", [])
            face_list = raw_faces.get("faces", []) if isinstance(raw_faces, dict) else raw_faces
            feature_counter = {}
            for face in face_list:
                idx = face.get("face_index", face_list.index(face))
                ftype = face.get("surface_type", "face").lower()
                feature_counter[ftype] = feature_counter.get(ftype, 0) + 1
                prefix_map = {"plane": "FACE", "cylinder": "BORE", "cone": "CONE",
                               "torus": "TORUS", "bspline": "SURF"}
                prefix = prefix_map.get(ftype, ftype[:4].upper())
                fid = f"{prefix}_{feature_counter[ftype]:03d}"
                annotations[idx] = {
                    "feature_id": fid,
                    "feature_type": ftype,
                    "inspection_section": "GENERAL",
                    "centroid_datum": None,
                }

    # Merge annotations into face geometry
    result = []
    for face in FACE_DATA:
        idx = face["face_index"]
        ann = annotations.get(idx, {
            "feature_id": f"FACE_{idx:03d}",
            "feature_type": face["face_type"],
            "inspection_section": "GENERAL",
            "centroid_datum": None,
        })
        result.append({**face, **ann})

    return jsonify({
        "step_file": os.path.basename(STEP_PATH),
        "face_count": len(result),
        "faces": result,
    })


@app.route("/api/model")
def get_model():
    global FACE_DATA
    if FACE_DATA is None:
        abort(503, "Model not loaded")
    # Send geometry — strip large arrays if already sent (client caches)
    return jsonify({
        "step_file": os.path.basename(STEP_PATH),
        "face_count": len(FACE_DATA),
        "faces": FACE_DATA,
    })


@app.route("/api/datums", methods=["GET"])
def get_datums():
    datum_path = Path(STEP_PATH).with_suffix(".datums.json")
    if datum_path.exists():
        with open(datum_path) as f:
            return jsonify(json.load(f))
    return jsonify({"datums": []})


@app.route("/api/datums", methods=["POST"])
def save_datums():
    data = request.get_json()
    if not data:
        abort(400, "No JSON body")

    datums = data.get("datums", [])
    step_hash = sha256_file(STEP_PATH)
    datum_path = Path(STEP_PATH).with_suffix(".datums.json")

    # Enrich each datum with face_type and normal from tessellation
    face_lookup = {f["face_index"]: f for f in FACE_DATA}
    enriched = []
    for d in datums:
        idx = d["face_index"]
        face = face_lookup.get(idx, {})
        enriched.append({
            "label": d["label"],
            "face_index": idx,
            "face_type": face.get("face_type", "unknown"),
            "normal": face.get("normal"),
            "centroid": face.get("centroid"),
        })

    output = {
        "step_file": os.path.basename(STEP_PATH),
        "step_file_hash": step_hash,
        "tagged_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "datums": enriched,
    }

    with open(datum_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[OK] Saved datums to {datum_path}")
    return jsonify({"saved": True, "path": str(datum_path)})


def main():
    global STEP_PATH, FACE_DATA, FEATURES_DATUMED_PATH

    if len(sys.argv) < 2:
        print("Usage: python server.py <file.step> [features_datumed.json]")
        sys.exit(1)

    STEP_PATH = os.path.abspath(sys.argv[1])
    if not os.path.exists(STEP_PATH):
        print(f"File not found: {STEP_PATH}")
        sys.exit(1)

    # Optional second arg: features_datumed.json for the feature map view
    if len(sys.argv) >= 3:
        FEATURES_DATUMED_PATH = os.path.abspath(sys.argv[2])
        print(f"[*] Feature map data: {FEATURES_DATUMED_PATH}")
    else:
        # Auto-detect: look for <stepname>_features_datumed.json alongside the STEP file
        auto = Path(STEP_PATH).with_name(Path(STEP_PATH).stem + "_features_datumed.json")
        if auto.exists():
            FEATURES_DATUMED_PATH = str(auto)
            print(f"[*] Auto-detected feature map data: {FEATURES_DATUMED_PATH}")

    print(f"[*] Loading and tessellating: {STEP_PATH}")
    print("[*] This may take a few seconds for large files...")
    FACE_DATA = tessellate_step(STEP_PATH)
    print(f"[OK] {len(FACE_DATA)} faces tessellated")
    print("[*] Datum tagger → http://localhost:5050")
    print("[*] Feature map   → http://localhost:5050/map")

    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5050/map")).start()
    app.run(host="127.0.0.1", port=5050, debug=False)


if __name__ == "__main__":
    main()
