#!/usr/bin/env python3
"""Export classified STEP features to the ShiaanX feature-viewer face contract."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
import os
import shutil
from typing import Any
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("classified_json", type=Path)
    parser.add_argument("--features-json", type=Path)
    parser.add_argument("--model-predictions-json", type=Path)
    parser.add_argument("--step-file", type=Path)
    parser.add_argument("--viewer-html", type=Path, default=Path("feature-viewer-package/viewer/step-viewer.html"))
    parser.add_argument("--part-name", default=None)
    parser.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "outputs" / "viewer_review")
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--label-source", choices=["rule", "model"], default="rule")
    parser.add_argument("--copy-step", action="store_true")
    parser.add_argument("--write-review-html", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def snake(value: str | None) -> str:
    return (value or "unknown").strip().lower().replace(" ", "_").replace("-", "_")


def viewer_feature_type(raw_type: str | None) -> str:
    """Map detailed classifier labels into the viewer's color-family vocabulary."""
    t = snake(raw_type)
    if t == "boss_angled":
        return "boss"
    if "slot" in t:
        return "slot"
    if "hole" in t or "bore" in t or t in {"counterbore", "countersink", "tapped"}:
        return t
    if "pocket" in t:
        return t
    if t in {"planar_face", "face"}:
        return "planar_face"
    if "chamfer" in t:
        return "chamfer"
    if t in {"stock", "background"}:
        return "background"
    return t


def inspection_section(feature_type: str) -> str:
    t = snake(feature_type)
    if "hole" in t or "bore" in t or t in {"counterbore", "countersink", "tapped"}:
        return "Bores"
    if "pocket" in t:
        return "Pockets"
    if t in {"planar_face", "face"}:
        return "Planar Faces"
    if t == "boss":
        return "Bosses"
    if t == "slot":
        return "Slots"
    if t == "chamfer":
        return "Chamfers"
    if t == "background":
        return "Background"
    return "Other"


def centroid_for_face(features_data: dict[str, Any] | None, face_index: int) -> dict[str, float] | None:
    if not features_data:
        return None
    faces = features_data.get("faces", {}).get("faces", [])
    if face_index < 0 or face_index >= len(faces):
        return None
    centroid = faces[face_index].get("centroid")
    if not isinstance(centroid, dict):
        return None
    return {
        axis: float(centroid[axis])
        for axis in ("x", "y", "z")
        if axis in centroid and centroid[axis] is not None
    }


def load_model_cluster_map(path: Path | None) -> dict[int, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    data = load_json(path)
    return {
        int(cluster["cluster_id"]): cluster
        for cluster in data.get("cluster_predictions", [])
        if cluster.get("cluster_id") is not None
    }


def feature_id_for(cluster: dict[str, Any], raw_type: str, label_source: str) -> str:
    cluster_id = int(cluster.get("cluster_id", 0))
    if label_source == "model":
        return f"model_{raw_type}_{cluster_id:03d}"
    return f"{raw_type}_{cluster_id:03d}"


def build_payload(
    classified_data: dict[str, Any],
    *,
    classified_path: Path,
    features_data: dict[str, Any] | None,
    features_path: Path | None,
    model_cluster_map: dict[int, dict[str, Any]],
    model_path: Path | None,
    step_file: Path | None,
    part_name: str,
    label_source: str,
) -> dict[str, Any]:
    faces_payload: list[dict[str, Any]] = []
    features_payload: list[dict[str, Any]] = []
    seen_faces: set[int] = set()

    for cluster in classified_data.get("clusters", []):
        cluster_id = int(cluster.get("cluster_id", 0))
        rule_raw_type = snake(cluster.get("feature_type") or cluster.get("seed_type"))
        model_cluster = model_cluster_map.get(cluster_id, {})
        model_raw_type = snake(model_cluster.get("model_label"))
        raw_type = model_raw_type if label_source == "model" and model_raw_type != "unknown" else rule_raw_type
        feature_type = viewer_feature_type(raw_type)
        section = inspection_section(feature_type)
        fid = feature_id_for(cluster, raw_type, label_source)
        face_indices = [int(index) for index in cluster.get("face_indices", [])]

        feature_row = {
            "feature_id": fid,
            "cluster_id": cluster_id,
            "feature_type": feature_type,
            "raw_feature_type": raw_type,
            "rule_feature_type": rule_raw_type,
            "inspection_section": section,
            "face_indices": face_indices,
            "face_count": len(face_indices),
            "confidence": cluster.get("confidence"),
            "seed_face_index": cluster.get("seed_face_index"),
            "seed_type": cluster.get("seed_type"),
            "depth": cluster.get("depth"),
            "radii": cluster.get("radii"),
            "model_majority_label": model_cluster.get("model_label"),
            "model_vote_fraction": model_cluster.get("vote_fraction"),
            "review_status": "",
            "review_label": "",
            "review_notes": "",
        }
        features_payload.append(feature_row)

        for face_index in face_indices:
            seen_faces.add(face_index)
            faces_payload.append(
                {
                    "feature_id": fid,
                    "feature_type": feature_type,
                    "raw_feature_type": raw_type,
                    "rule_feature_type": rule_raw_type,
                    "inspection_section": section,
                    "face_index": face_index,
                    "centroid": centroid_for_face(features_data, face_index),
                    "confidence": cluster.get("confidence"),
                    "cluster_id": cluster_id,
                    "model_majority_label": model_cluster.get("model_label"),
                    "model_vote_fraction": model_cluster.get("vote_fraction"),
                }
            )

    face_total = None
    if features_data:
        face_total = features_data.get("faces", {}).get("total_faces")
    if face_total is None:
        face_total = max(seen_faces) + 1 if seen_faces else 0

    return {
        "metadata": {
            "part_name": part_name,
            "step_file": str(step_file) if step_file else classified_data.get("file"),
            "source_classified_json": str(classified_path),
            "source_features_json": str(features_path) if features_path else None,
            "source_model_predictions_json": str(model_path) if model_path else None,
            "label_source": label_source,
            "face_contract": "One row per face for FeatureMapTab: feature_id, feature_type, inspection_section, face_index, centroid.",
            "accuracy_note": (
                "This is review output, not ground truth. The reviewer should fill review_status/review_label/review_notes "
                "in the CSV or use the feature groups visually."
            ),
            "feature_count": len(features_payload),
            "face_rows": len(faces_payload),
            "total_faces_in_step_extraction": int(face_total),
            "covered_face_count": len(seen_faces),
            "missing_face_count": max(int(face_total) - len(seen_faces), 0),
        },
        "faces": sorted(faces_payload, key=lambda row: (int(row["cluster_id"]), int(row["face_index"]))),
        "features": sorted(features_payload, key=lambda row: int(row["cluster_id"])),
    }


def write_csv(path: Path, features: list[dict[str, Any]]) -> None:
    fields = [
        "feature_id",
        "cluster_id",
        "feature_type",
        "raw_feature_type",
        "rule_feature_type",
        "inspection_section",
        "face_count",
        "face_indices",
        "confidence",
        "model_majority_label",
        "model_vote_fraction",
        "review_status",
        "review_label",
        "review_notes",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for feature in features:
            row = {field: feature.get(field) for field in fields}
            row["face_indices"] = " ".join(str(index) for index in feature.get("face_indices", []))
            writer.writerow(row)


def write_summary(path: Path, payload: dict[str, Any], json_path: Path, csv_path: Path, html_path: Path | None) -> None:
    counts: dict[str, int] = {}
    for feature in payload["features"]:
        raw_type = feature["raw_feature_type"]
        counts[raw_type] = counts.get(raw_type, 0) + 1

    lines = [
        f"# {payload['metadata']['part_name']} Feature Review Export",
        "",
        "This export is for visual/human review. It is not a ground-truth accuracy report.",
        "",
        "## Files",
        "",
        f"- Viewer JSON: `{json_path}`",
        f"- Reviewer CSV: `{csv_path}`",
    ]
    if html_path:
        lines.append(f"- Static review page: `{html_path}`")

    metadata = payload["metadata"]
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Label source: {metadata['label_source']}",
            f"- Features: {metadata['feature_count']}",
            f"- Face rows: {metadata['face_rows']}",
            f"- Covered faces: {metadata['covered_face_count']} / {metadata['total_faces_in_step_extraction']}",
            f"- Missing faces: {metadata['missing_face_count']}",
            "",
            "## Feature Counts",
            "",
            "| Raw feature type | Features |",
            "| --- | ---: |",
        ]
    )
    for feature_type, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {feature_type} | {count} |")

    lines.extend(
        [
            "",
            "## Review Guidance",
            "",
            "Use the JSON with `feature-viewer-package` or open the static review page from a local HTTP server. Mark the CSV columns `review_status`, `review_label`, and `review_notes`; those annotations become the ground truth for this real part.",
            "",
            "The `model_majority_label` column is from the trained MFCAD++ model and is included only for comparison. It should not be treated as correctness because the 25-class MFCAD++ taxonomy does not include production labels such as boss, counterbore, large_bore, or planar_face.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def write_review_html(path: Path, *, payload: dict[str, Any], json_path: Path, viewer_html: Path, step_path: Path | None) -> None:
    rel_json = quote(json_path.name)
    rel_viewer = quote(os.path.relpath(viewer_html.resolve(), path.parent.resolve()))

    viewer_src = rel_viewer
    if step_path:
        try:
            step_rel = step_path.resolve().relative_to(path.parent.resolve()).as_posix()
            viewer_src += "?url=" + quote(step_rel)
        except ValueError:
            viewer_src += "?url=" + quote(step_path.resolve().as_uri(), safe=":/")

    title = html.escape(payload["metadata"]["part_name"])
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} Feature Review</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #101319; color: #e7edf7; }}
    .app {{ display: grid; grid-template-columns: minmax(0, 1fr) 360px; height: 100vh; }}
    iframe {{ width: 100%; height: 100%; border: 0; background: #0d0f12; }}
    aside {{ border-left: 1px solid #2a3142; background: #151a23; overflow: hidden; display: flex; flex-direction: column; }}
    header {{ padding: 14px 16px; border-bottom: 1px solid #2a3142; }}
    h1 {{ font-size: 15px; margin: 0 0 6px; }}
    .meta {{ font-size: 12px; color: #9aa7bd; line-height: 1.4; }}
    #search {{ margin-top: 12px; width: 100%; padding: 8px; border: 1px solid #30384b; background: #0f131a; color: #e7edf7; border-radius: 4px; }}
    #list {{ overflow: auto; flex: 1; }}
    .section {{ position: sticky; top: 0; padding: 7px 16px; background: #202739; color: #aab5c9; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }}
    .item {{ padding: 10px 16px; border-bottom: 1px solid #252c3c; cursor: pointer; display: grid; grid-template-columns: 1fr auto; gap: 6px; }}
    .item:hover, .item.active {{ background: #263044; }}
    .fid {{ font: 600 12px ui-monospace, SFMono-Regular, Menlo, monospace; color: #f4f7fb; }}
    .type {{ font-size: 12px; color: #9aa7bd; }}
    .count {{ font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; color: #9aa7bd; }}
    footer {{ padding: 10px 16px; border-top: 1px solid #2a3142; color: #9aa7bd; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="app">
    <iframe id="viewer" src="{viewer_src}"></iframe>
    <aside>
      <header>
        <h1>{title}</h1>
        <div class="meta">{payload['metadata']['feature_count']} features, {payload['metadata']['covered_face_count']} covered faces. Click a feature to highlight its faces.</div>
        <input id="search" placeholder="Search type or feature id">
      </header>
      <div id="list"></div>
      <footer>JSON: {html.escape(json_path.name)}</footer>
    </aside>
  </div>
  <script>
    const viewer = document.getElementById('viewer');
    const list = document.getElementById('list');
    const search = document.getElementById('search');
    let features = [];
    let active = null;

    function highlight(feature) {{
      active = feature.feature_id === active ? null : feature.feature_id;
      const selected = active ? features.find(f => f.feature_id === active) : null;
      viewer.contentWindow.postMessage({{ type: 'highlight', faceIndices: selected ? selected.face_indices : [] }}, '*');
      render();
    }}

    function render() {{
      const q = search.value.toLowerCase();
      const rows = features.filter(f => !q || f.feature_id.toLowerCase().includes(q) || f.raw_feature_type.toLowerCase().includes(q));
      const groups = {{}};
      for (const f of rows) (groups[f.inspection_section] ||= []).push(f);
      list.innerHTML = '';
      for (const section of Object.keys(groups).sort()) {{
        const head = document.createElement('div');
        head.className = 'section';
        head.textContent = `${{section}} (${{groups[section].length}})`;
        list.appendChild(head);
        for (const f of groups[section]) {{
          const item = document.createElement('div');
          item.className = 'item' + (f.feature_id === active ? ' active' : '');
          item.innerHTML = `<div><div class="fid">${{f.feature_id}}</div><div class="type">${{f.raw_feature_type.replaceAll('_', ' ')}}</div></div><div class="count">${{f.face_count}}f</div>`;
          item.onclick = () => highlight(f);
          list.appendChild(item);
        }}
      }}
    }}

    fetch('{rel_json}')
      .then(r => r.json())
      .then(data => {{ features = data.features || []; render(); }})
      .catch(err => {{ list.innerHTML = '<div style="padding:16px;color:#ff8a8a">Could not load JSON. Serve this folder with a local HTTP server.</div>'; console.error(err); }});
    search.addEventListener('input', render);
  </script>
</body>
</html>
"""
    path.write_text(document)


def main() -> int:
    args = parse_args()
    classified_path = args.classified_json.expanduser().resolve()
    features_path = args.features_json.expanduser().resolve() if args.features_json else None
    model_path = args.model_predictions_json.expanduser().resolve() if args.model_predictions_json else None
    step_file = args.step_file.expanduser().resolve() if args.step_file else None
    viewer_html = args.viewer_html.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    classified_data = load_json(classified_path)
    features_data = load_json(features_path) if features_path else None
    model_cluster_map = load_model_cluster_map(model_path)
    part_name = args.part_name or Path(classified_data.get("file", classified_path.stem)).stem
    prefix = args.prefix or part_name.replace(" ", "_")

    copied_step = None
    if args.copy_step and step_file:
        copied_step = out_dir / step_file.name.replace(" ", "_")
        shutil.copy2(step_file, copied_step)

    payload = build_payload(
        classified_data,
        classified_path=classified_path,
        features_data=features_data,
        features_path=features_path,
        model_cluster_map=model_cluster_map,
        model_path=model_path,
        step_file=step_file,
        part_name=part_name,
        label_source=args.label_source,
    )

    json_path = out_dir / f"{prefix}_viewer_faces.json"
    csv_path = out_dir / f"{prefix}_feature_review.csv"
    summary_path = out_dir / f"{prefix}_review_summary.md"
    html_path = out_dir / f"{prefix}_review.html" if args.write_review_html else None
    bundled_viewer_html = out_dir / "step-viewer.html"

    json_path.write_text(json.dumps(payload, indent=2) + "\n")
    write_csv(csv_path, payload["features"])
    if html_path:
        shutil.copy2(viewer_html, bundled_viewer_html)
        write_review_html(
            html_path,
            payload=payload,
            json_path=json_path,
            viewer_html=bundled_viewer_html,
            step_path=copied_step or step_file,
        )
    write_summary(summary_path, payload, json_path, csv_path, html_path)

    print(
        json.dumps(
            {
                "viewer_json": str(json_path),
                "review_csv": str(csv_path),
                "summary": str(summary_path),
                "review_html": str(html_path) if html_path else None,
                "copied_step": str(copied_step) if copied_step else None,
                "feature_count": payload["metadata"]["feature_count"],
                "covered_faces": payload["metadata"]["covered_face_count"],
                "missing_faces": payload["metadata"]["missing_face_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
