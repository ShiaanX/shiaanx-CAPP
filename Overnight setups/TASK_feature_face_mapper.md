# Overnight Task — Feature-Face Mapper (Pipeline Stage 10a)

## Context (read this first)

Read `CLAUDE.md` and `SESSION_STATE.md` in the repo root before doing anything.

**What this builds:** A new pipeline module `10a. feature_face_mapper.py` that cross-references the CAM operation data in `*_params.json` against the raw face geometry in `*_features.json` and cluster data in `*_classified.json` to produce a definitive mapping:

```
CAM operation → STEP face cluster → raw face indices
```

This is the critical labelling link: it automatically generates ground-truth `(feature_type, cluster_id, face_indices)` records for every completed job, which feed the ML classifier as training data. It also powers the FeatureMapTab in the frontend to show face-level feature highlighting grounded in actual CAM intent.

**Working directory for pipeline scripts:** `Claude output for program sheet/`
**Python environment:** `C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe`
**Branch:** create `feature/feature-face-mapper`, branch off main

---

## Data structures available (study these before writing any code)

### `*_features.json` — raw face geometry from STEP

Top-level keys: `file`, `topology_counts`, `bounding_box`, `mass_properties`, `surface_area`, `faces`, `edges`, `vertices`, `holes_detected`, `is_valid`, `face_adjacency`

`faces` is a list indexed by face index (index 0 = face 0). Each entry:

```json
{ "surface_type": "Cylinder",
  "area": 34.38,
  "orientation": "Forward",
  "cylinder": {
    "radius": 4.0,
    "axis_direction": {"x": 0.0, "y": 0.0, "z": 1.0},
    "axis_location": {"x": -23.0, "y": 27.68, "z": 0.0}
  }
}
```

Surface types: `Plane`, `Cylinder`, `Cone`, `Torus`, `BSpline`, `Sphere`

For `Plane` faces:
```json
{ "surface_type": "Plane",
  "area": 150.2,
  "orientation": "Forward",
  "plane": {
    "normal": {"x": 0.0, "y": 0.0, "z": 1.0},
    "location": {"x": 5.0, "y": 5.0, "z": 25.4}
  }
}
```

### `*_classified.json` — feature clusters

Top-level keys: `clusters`, `file`, `bounding_box`, `mass_properties`, `surface_area`, `topology_counts`

Each cluster:
```json
{
  "cluster_id": 3,
  "seed_face_index": 10,
  "face_indices": [2, 10, 11],
  "face_count": 3,
  "feature_axis": [0.0, 0.0, 1.0],
  "depth": 3.87,
  "radii": [1.26, 4.0],
  "is_principal_axis": true,
  "feature_type": "counterbore",
  "confidence": "high"
}
```

### `*_setups.json` — WCS per setup

Each setup has:
```json
{
  "setup_id": 1,
  "axis_label": "-Z approach",
  "spindle_direction": [0.0, 0.0, -1.0],
  "wcs_origin_mm": {"x": 0.0, "y": 0.0, "z": 25.4},
  "wcs_code": "G54",
  "features": [...]
}
```

The `features` array inside each setup contains `cluster_id` values assigned to that setup.

### `*_params.json` — operations with dimensions

Top-level keys: `clusters`, plus metadata. Each cluster has a `process_sequence` list. Each operation:
```json
{
  "operation": "twist_drill",
  "tool_diameter": 4.0,
  "depth": 3.87,
  "feed_rate": 382.0,
  "rpm": 15000,
  "setup_id": 1
}
```

The `cluster_id` is the key under which operations appear.

---

## The matching algorithm

### Step 1 — Build face geometry index

For each face in `*_features.json`, extract its centroid and key geometry:

```python
def build_face_index(features_json):
    """
    Returns dict: face_index -> {
        surface_type, area, centroid: {x,y,z},
        radius (for cylinders), axis (for cylinders/cones),
        normal (for planes), z_level (for planes)
    }
    """
    index = {}
    for i, face in enumerate(features_json.get('faces', [])):
        st = face.get('surface_type')
        entry = {'surface_type': st, 'area': face.get('area', 0)}

        if st == 'Cylinder':
            cyl = face.get('cylinder', {})
            loc = cyl.get('axis_location', {})
            entry['radius'] = cyl.get('radius')
            entry['axis'] = cyl.get('axis_direction', {})
            entry['centroid'] = {'x': loc.get('x', 0), 'y': loc.get('y', 0), 'z': loc.get('z', 0)}

        elif st == 'Plane':
            pl = face.get('plane', {})
            loc = pl.get('location', {})
            entry['normal'] = pl.get('normal', {})
            entry['z_level'] = loc.get('z', 0)
            entry['centroid'] = loc

        elif st in ('Torus', 'Cone', 'BSpline', 'Sphere'):
            # Use area-weighted centroid placeholder — flag as uncertain
            entry['centroid'] = None
            entry['uncertain'] = True

        index[i] = entry
    return index
```

### Step 2 — Build cluster geometry summaries

For each cluster in `*_classified.json`, compute:
- **centroid**: mean of face centroids for all cylinder faces in the cluster (the axis_location of the primary cylindrical face). For plane clusters, use the plane location.
- **primary_radius**: `radii[0]` if present
- **depth**: from cluster `depth`
- **axis**: from cluster `feature_axis`

```python
def compute_cluster_geometry(cluster, face_index):
    """
    Returns: { centroid, primary_radius, depth, axis, face_types }
    """
    face_types = set()
    cylinder_locs = []
    plane_z_levels = []

    for fi in cluster.get('face_indices', []):
        entry = face_index.get(fi, {})
        st = entry.get('surface_type')
        face_types.add(st)
        if st == 'Cylinder' and entry.get('centroid'):
            cylinder_locs.append(entry['centroid'])
        if st == 'Plane' and entry.get('z_level') is not None:
            plane_z_levels.append(entry['z_level'])

    centroid = None
    if cylinder_locs:
        centroid = {
            'x': sum(c['x'] for c in cylinder_locs) / len(cylinder_locs),
            'y': sum(c['y'] for c in cylinder_locs) / len(cylinder_locs),
            'z': sum(c['z'] for c in cylinder_locs) / len(cylinder_locs),
        }
    elif plane_z_levels:
        centroid = {'x': None, 'y': None, 'z': sum(plane_z_levels) / len(plane_z_levels)}

    radii = cluster.get('radii', [])
    return {
        'centroid': centroid,
        'primary_radius': radii[0] if radii else None,
        'all_radii': radii,
        'depth': cluster.get('depth'),
        'axis': cluster.get('feature_axis', [0, 0, 1]),
        'face_types': list(face_types),
    }
```

### Step 3 — Match operations to clusters

For each operation in `*_params.json`, find the best-matching cluster using this priority:

**Rule 1 — Exact cluster match (trivial case):**
The params.json is already keyed by `cluster_id`. Each operation in `cluster_id: 5` already belongs to cluster 5. So for operations, the `cluster_id → face_indices` mapping is **already known from classified.json**. The real work is confirming the geometric consistency and flagging mismatches.

Wait — re-read the params.json structure. The operations are nested under cluster_id keys. So:
- `params['clusters'][5]['process_sequence']` → list of operations for cluster 5
- `classified['clusters'][5]['face_indices']` → face indices for cluster 5

**The mapping already exists implicitly.** What this module adds:

1. **Enrich** each cluster with its face-level geometry (centroid XY, radius, depth in CAD space)
2. **Convert** CAD-space coordinates to WCS coordinates for each setup
3. **Validate** that the assigned feature_type matches what the geometry says (catches classification errors)
4. **Output** the explicit `operation_id → {cluster_id, face_indices, wcs_position, confidence}` map

The full matching output for each cluster × operation:

```python
def match_operation_to_geometry(op, cluster, cluster_geom, wcs_origin):
    """
    Returns confidence: 'high' | 'medium' | 'low' | 'unmatched'
    and a dict of matched geometry fields.
    """
    matches = {}
    confidence_score = 0

    op_type = op.get('operation', '')
    ftype = cluster.get('feature_type', '')

    # Operation → feature type consistency
    OP_TO_FTYPE = {
        'twist_drill': ['through_hole', 'blind_hole', 'tapped_hole'],
        'spot_drill': ['through_hole', 'blind_hole', 'tapped_hole', 'counterbore', 'countersink'],
        'core_drill': ['through_hole', 'blind_hole'],
        'tap_rh': ['tapped_hole'],
        'pocket_mill': ['pocket', 'rectangular_pocket', 'slot', 'rectangular_slot'],
        'contour_mill': ['boss', 'cylindrical_boss'],
        'face_mill': ['planar_face', 'face'],
        'chamfer_mill': ['chamfer'],
        'boring_bar': ['large_bore'],
        'circular_interp': ['large_bore', 'through_hole'],
        'ball_nose': ['pocket', 'rectangular_pocket'],
    }
    valid_ftypes = OP_TO_FTYPE.get(op_type, [])
    if ftype in valid_ftypes:
        confidence_score += 3
        matches['feature_type'] = ftype
    else:
        matches['feature_type_mismatch'] = f"op={op_type} expects {valid_ftypes}, cluster has {ftype}"

    # Radius / diameter match
    op_dia = op.get('tool_diameter')
    cg_radius = cluster_geom.get('primary_radius')
    if op_dia and cg_radius:
        op_radius = op_dia / 2.0
        if abs(op_radius - cg_radius) < 0.3:  # 0.3mm tolerance
            confidence_score += 3
            matches['radius_match'] = round(cg_radius, 3)
        elif abs(op_radius - cg_radius) < 1.0:
            confidence_score += 1
            matches['radius_approximate'] = round(cg_radius, 3)

    # Depth match
    op_depth = op.get('depth') or op.get('ap')
    cg_depth = cluster_geom.get('depth')
    if op_depth and cg_depth and abs(op_depth - cg_depth) < 0.5:
        confidence_score += 2
        matches['depth_match'] = round(cg_depth, 3)

    # WCS position (centroid in WCS)
    cg_centroid = cluster_geom.get('centroid')
    if cg_centroid and wcs_origin:
        wcs_x = (cg_centroid.get('x') or 0) - (wcs_origin.get('x') or 0)
        wcs_y = (cg_centroid.get('y') or 0) - (wcs_origin.get('y') or 0)
        wcs_z = (cg_centroid.get('z') or 0) - (wcs_origin.get('z') or 0)
        matches['wcs_position'] = {'x': round(wcs_x, 3), 'y': round(wcs_y, 3), 'z': round(wcs_z, 3)}

    if confidence_score >= 5:
        confidence = 'high'
    elif confidence_score >= 3:
        confidence = 'medium'
    elif confidence_score >= 1:
        confidence = 'low'
    else:
        confidence = 'unmatched'

    return confidence, matches
```

### Step 4 — Assemble output

```python
OUTPUT_SCHEMA = {
    "source_file": "<part name>.step",
    "generated": "<ISO timestamp>",
    "clusters": {
        "<cluster_id>": {
            "feature_type": "through_hole",
            "face_indices": [2, 10, 11],
            "geometry": {
                "centroid_cad": {"x": -23.0, "y": 27.7, "z": 0.0},
                "primary_radius": 4.0,
                "depth": 3.87,
                "axis": [0.0, 0.0, 1.0]
            },
            "setups": {
                "1": {
                    "wcs_code": "G54",
                    "wcs_position": {"x": -23.0, "y": 27.7, "z": -3.87},
                    "operations": [
                        {
                            "op_index": 0,
                            "operation": "spot_drill",
                            "tool_diameter": 6.0,
                            "confidence": "high",
                            "matches": {"feature_type": "through_hole", "radius_match": 4.0}
                        },
                        {
                            "op_index": 1,
                            "operation": "twist_drill",
                            "tool_diameter": 8.0,
                            "confidence": "high",
                            "matches": {"feature_type": "through_hole", "radius_match": 4.0, "depth_match": 3.87}
                        }
                    ]
                }
            },
            "overall_confidence": "high",
            "review_required": false
        }
    },
    "summary": {
        "total_clusters": 45,
        "high_confidence": 38,
        "medium_confidence": 5,
        "low_confidence": 2,
        "review_required": 2
    }
}
```

---

## Implementation steps

### Step 1 — Write `10a. feature_face_mapper.py`

Location: `Claude output for program sheet/10a. feature_face_mapper.py`

Function signature:
```python
def map_features(
    features_json: dict,
    classified_json: dict,
    setups_json: dict,
    params_json: dict,
) -> dict:
    """
    Returns the feature_face_map dict.
    """
```

And a `main()` that accepts a path to any of the pipeline JSONs and infers the others by filename stem:
```python
# Usage: python "10a. feature_face_mapper.py" "path/to/PART_params.json"
```

Use the helper import pattern (importlib.util) if you need geometry_utils. Otherwise keep it self-contained.

Also create the shim: `feature_face_mapper.py` (7-line importlib shim, same pattern as other shims).

### Step 2 — Integrate into `10. run_pipeline.py`

After the params stage (stage 7 / `8. parameter_calculation.py`), add stage 7.5:

```python
# Stage 7.5 — Feature-face mapping
log("Running feature-face mapper...")
feature_face_map_path = run_stage(
    "10a. feature_face_mapper",
    input_path=params_path,
    output_suffix="_feature_face_map",
)
```

The mapper reads params and the other JSONs automatically (same stem), writes `*_feature_face_map.json` to the same folder.

If the mapper fails (e.g. OCC not needed but some import is missing), log a warning and continue — this stage is non-blocking.

### Step 3 — Add backend endpoint to `capp_service/main.py`

```python
@app.get('/jobs/{job_id}/feature_face_map')
def get_feature_face_map(job_id: str):
    """Return the feature-face mapping JSON."""
    job_dir = JOBS_DIR / job_id
    matches = list(job_dir.glob('*_feature_face_map.json'))
    if not matches:
        return {'clusters': {}, 'summary': {'total_clusters': 0}}
    with open(matches[0], encoding='utf-8') as f:
        return json.load(f)
```

Also update `GET /jobs/{job_id}/faces` to PREFER the feature_face_map over classified.json if available, so face colours in the FeatureMapTab reflect confirmed CAM assignments:

```python
@app.get('/jobs/{job_id}/faces')
def get_faces(job_id: str):
    job_dir = JOBS_DIR / job_id
    # Prefer feature_face_map (richer, CAM-confirmed)
    ffm_matches = list(job_dir.glob('*_feature_face_map.json'))
    if ffm_matches:
        with open(ffm_matches[0], encoding='utf-8') as f:
            ffm = json.load(f)
        faces = []
        for cid, cdata in ffm.get('clusters', {}).items():
            ftype = cdata.get('feature_type', 'unknown')
            section = _INSPECTION_SECTION.get(ftype, 'Other')
            for fi in cdata.get('face_indices', []):
                faces.append({
                    'feature_id': str(cid),
                    'feature_type': ftype,
                    'inspection_section': section,
                    'face_index': fi,
                    'centroid': cdata.get('geometry', {}).get('centroid_cad'),
                    'wcs_position': cdata.get('setups', {}).get('1', {}).get('wcs_position'),
                    'confidence': cdata.get('overall_confidence', 'medium'),
                    'review_required': cdata.get('review_required', False),
                })
        return {'faces': faces, 'source': 'feature_face_map'}
    # Fall back to classified.json
    ...  # existing code
```

### Step 4 — Update `FeatureMapTab.js` to use confidence + WCS position

The `/faces` endpoint now returns `confidence` and `wcs_position` per face. Update the display to:
- Show a `⚠` flag next to features with `review_required: true`
- Show WCS position (x, y, z) in the feature detail when a feature is clicked
- Show confidence badge (HIGH / MED / LOW) in the feature list

In the feature list item (around line 125 of FeatureMapTab.js), add:
```jsx
{f.review_required && <span style={{ color: '#c0392b', fontSize: 10 }}>⚠ REVIEW</span>}
{f.confidence && (
  <span style={{ fontSize: 10, color: f.confidence === 'high' ? '#27ae60' : f.confidence === 'medium' ? '#f39c12' : '#e74c3c' }}>
    {f.confidence.toUpperCase()}
  </span>
)}
```

Read the full FeatureMapTab.js before editing — understand the exact component structure.

### Step 5 — Test on Motor Mount

Run the mapper standalone on the existing Motor Mount outputs:

```powershell
$base = "C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet\Manufactured parts\Motor Mount"
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" "C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet\10a. feature_face_mapper.py" "$base\MOTOR MOUNT_params.json"
```

Expected output: `MOTOR MOUNT_feature_face_map.json` in the same folder.

Verify:
- Summary shows reasonable numbers (most clusters should be high confidence)
- `review_required: true` only for BSpline-heavy clusters or geometry mismatches
- WCS positions look physically plausible (XY within part bounding box, Z = depth from datum)

Then copy the output to the live job folder for the capp_service to serve:
```powershell
Copy-Item "$base\MOTOR MOUNT_feature_face_map.json" "C:\Users\Siddhant Gupta\Documents\ShiaanX\capp_service\jobs\4a3fa7d1-a032-44dd-9759-9c0daa1549c3\MOTOR_MOUNT_feature_face_map.json"
```

Check the FeatureMapTab in the browser — features should now show confidence badges and WCS positions.

### Step 6 — Update SESSION_STATE.md

Add a new section `## Feature-Face Mapper (Stage 10a)`:
- What the module does and its output schema
- Where it lives (`10a. feature_face_mapper.py` + shim)
- How confidence is computed
- How it integrates with the pipeline runner and capp_service
- How to run it standalone
- Accuracy summary from Motor Mount test run

Write `audit/SESSION_UPDATE_feature_face_mapper.md` with completion status and any blockers.

---

## What NOT to do

- Do not use PythonOCC — pure Python + JSON only. No STEP file reading needed (features.json already has all geometry).
- Do not modify `1. extract_features.py` through `9. program_sheet.py` — the mapper reads their outputs only.
- Do not add centroid computation via OCC — use the `axis_location` and `plane.location` fields already in features.json.
- Do not block the pipeline if the mapper fails — log warning and continue.
- Do not redesign the FeatureMapTab from scratch — add confidence badges and WCS position inline to existing component.

---

## Commit instructions

```bash
git checkout -b feature/feature-face-mapper
# do the work
git add "Claude output for program sheet/10a. feature_face_mapper.py" "Claude output for program sheet/feature_face_mapper.py" capp_service/main.py capp-frontend/src/components/viewer/tabs/FeatureMapTab.js audit/ SESSION_STATE.md
git commit -m "feat(mapper): feature-face mapper stage 10a with confidence scoring and WCS positions"
git push origin feature/feature-face-mapper
```
