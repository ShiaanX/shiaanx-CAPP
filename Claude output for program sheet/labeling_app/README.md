# CAD Feature Recognition Local App

This package runs the STEP recognition and manual face-labeling workflows on one
computer. It includes the trained MFCAD++ checkpoint, inference code, OCP STEP
extractor, viewer, and 25-class label definitions.

**Lives inside `shiaanx-CAPP`, one level under `Claude output for program sheet/`.**
The clustering step calls `../2. cluster_features.py` directly — the real pipeline
script, not a vendored copy — so this folder must stay where it is relative to the
rest of the repo. Do not copy it out on its own.

## Requirements

- 64-bit Windows, macOS, or Linux
- Python 3.11 or newer; Python 3.11 or 3.12 is recommended
- Internet access during setup to download Python packages
- Internet access while viewing STEP geometry because the viewer loads Three.js
  and `occt-import-js` from public CDNs
- Several GB of free disk space for PyTorch/OCP and the virtual environment

The full MFCAD++ dataset is not needed. The trained checkpoint and label names
are already included.

## macOS / Linux

Open Terminal in this unzipped folder and run:

```bash
chmod +x setup.sh run.sh
./setup.sh
./run.sh
```

Then open [http://127.0.0.1:8780](http://127.0.0.1:8780).

Manual labeling is available at
[http://127.0.0.1:8780/label](http://127.0.0.1:8780/label).

## Windows

Open Command Prompt in this unzipped folder and run:

```bat
setup.bat
run.bat
```

Then open `http://127.0.0.1:8780`.

## Manual Commands

Use these if the helper scripts are unavailable:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python check_install.py
python -m uvicorn local_app.main:app --host 127.0.0.1 --port 8780
```

On Windows, activate with `.venv\Scripts\activate` instead.

## Usage

1. Keep the terminal running while using the app.
2. Open the recognition page and upload a `.step` or `.stp` file.
3. Wait for extraction, clustering, model inference, and report generation.
4. Select a recognized feature to highlight its exact B-Rep faces.
5. Use the separate manual-labeling page for open-vocabulary ground truth.
6. Click several surfaces, or Shift-drag a rectangle, and create one feature
   instance from the complete selection. A slot can therefore contain its two
   radius surfaces and two plane surfaces in one annotation.
7. Reopen a feature-instance row to edit its complete surface group.
8. Save and download JSON or CSV. Custom label names are remembered as local
   suggestions for later parts.
9. Stop the server with `Ctrl+C` in the terminal.

Generated files are stored under `local_app/jobs/` and
`local_app/labeling_jobs/`. These folders are created automatically.

The annotation JSON uses `annotation_unit: "feature_instance"`. Each item has a
stable `feature_instance_id`, one label, and `surface_indices`/`face_indices`
containing every B-Rep surface that belongs to that feature. The CSV repeats the
same feature-instance ID on each member-surface row so the grouping is preserved.

## Model Metric

The bundled `hier_v1_model.pt` checkpoint achieved 93.82% face-classification
accuracy on the held-out MFCAD++ validation split. This number is not an accuracy
measurement for arbitrary uploaded STEP files. Raw STEP performance also depends
on the OCP-to-MFCAD++ graph adapter and whether the part's feature vocabulary is
covered by the 25 training classes.

## Troubleshooting

- `Address already in use`: stop the other service or run `PORT=8781 ./run.sh`.
- `No matching distribution found`: use a current 64-bit Python 3.11/3.12 build.
- Viewer remains blank: verify internet access and browser access to CDN assets.
- Setup fails on managed machines: ask the administrator to allow PyPI package
  downloads for PyTorch and `cadquery-ocp`.
