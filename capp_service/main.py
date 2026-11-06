import sys
import uuid
import os
import subprocess
import tempfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import aiofiles
import json

from runner import start_pipeline, STAGE_OUTPUTS

sys.path.insert(0, str(Path(__file__).parent.parent))
import job_manifest

app = FastAPI(title='ShiaanX CAPP Service')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

JOBS_DIR = Path(__file__).parent / 'jobs'
JOBS_DIR.mkdir(exist_ok=True)

_SOFT_JAW_GENERATOR = str(
    Path(__file__).parent.parent /
    'Claude output for program sheet' / 'fixture_design' / 'soft_jaw_generator.py'
)
_INSPECTION_TEMPLATE_GENERATOR = str(Path(__file__).parent.parent / 'inspection' / 'template_generator.py')
_DATUM_TRANSFORM = str(Path(__file__).parent.parent / 'datum_transform' / 'datum_transform.py')

# In-memory job store: { job_id: { status, stage, stage_name, outputs, error } }
# Rehydrated from each job folder's job.json + on-disk artifacts on startup so
# job state survives a service restart (previously in-memory only — see
# job_manifest.py for why).
jobs: dict = {}


def _hydrate_jobs_from_disk():
    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        manifest = job_manifest.load(job_dir)
        if manifest is None:
            continue
        outputs = {}
        for _, _, suffix in STAGE_OUTPUTS:
            matches = list(job_dir.glob(f'*{suffix}'))
            if not matches:
                continue
            key = suffix.lstrip('_').replace('.json', '').replace('.pdf', '')
            if suffix.endswith('.json'):
                try:
                    with open(matches[0], encoding='utf-8') as f:
                        outputs[key] = json.load(f)
                except Exception:
                    pass
            elif suffix.endswith('.pdf'):
                outputs['pdf_path'] = str(matches[0])
        jobs[manifest['job_id']] = {
            'job_id': manifest['job_id'],
            'part_name': manifest.get('part_name', 'Part'),
            'material': manifest.get('material', 'aluminium'),
            'status': manifest.get('pipeline_status', 'COMPLETE' if 'pdf_path' in outputs else 'UNKNOWN'),
            'stage': manifest.get('pipeline_stage', 9 if 'pdf_path' in outputs else 0),
            'stage_name': manifest.get('pipeline_stage_name', 'complete' if 'pdf_path' in outputs else 'unknown'),
            'outputs': outputs,
            'error': manifest.get('pipeline_error'),
        }


_hydrate_jobs_from_disk()


@app.post('/jobs')
async def create_job(
    step_file: UploadFile = File(...),
    part_name: str = Form('Part'),
    material: str = Form('aluminium'),
):
    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()

    filename = step_file.filename or 'part.step'
    # Browser uploads often omit part_name — fall back to the uploaded file's stem
    # (e.g. "MOTOR MOUNT") rather than the generic 'Part', so the job can be mapped
    # to its real part folder (demo_modules/part_data.py).
    if (not part_name or part_name == 'Part') and step_file.filename:
        part_name = Path(filename).stem
    safe_name = part_name.replace(' ', '_') or Path(filename).stem
    step_path = job_dir / f'{safe_name}.step'

    async with aiofiles.open(step_path, 'wb') as f:
        content = await step_file.read()
        await f.write(content)

    jobs[job_id] = {
        'job_id': job_id,
        'part_name': part_name,
        'material': material,
        'status': 'RUNNING',
        'stage': 0,
        'stage_name': 'queued',
        'outputs': {},
        'error': None,
    }
    job_manifest.create_job(job_dir, job_id, part_name, material, status='QUEUED')
    job_manifest.update_fields(job_dir, original_filename=filename)

    start_pipeline(job_id, str(step_path), material, part_name, jobs)
    # Demo analyses run in the background too, so /dfm, /quote and /cmm are warm
    # by the time the UI asks for them. Never blocks the upload response.
    _start_demo_background(job_id, job_dir)

    return {'job_id': job_id, 'part_name': part_name, 'original_filename': filename}


@app.get('/jobs/{job_id}')
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail='Job not found')
    job = jobs[job_id]

    # Piggyback manifest persistence on the status poll the frontend already does
    # continuously while a job runs — cheaper than adding a dedicated sync thread,
    # and it means job.json stays current without slowing down the pipeline itself.
    job_dir = JOBS_DIR / job_id
    try:
        job_manifest.update_fields(
            job_dir,
            pipeline_status=job['status'],
            pipeline_stage=job['stage'],
            pipeline_stage_name=job['stage_name'],
            pipeline_error=job['error'],
        )
        job_manifest.refresh_artifacts(job_dir)
    except FileNotFoundError:
        pass  # job predates job_manifest.py — nothing to sync yet

    # Don't return the full outputs in the status poll — too large
    # Return only metadata + lightweight classified/setups/params summaries
    return {
        'job_id': job_id,
        'part_name': job['part_name'],
        'material': job['material'],
        'status': job['status'],
        'stage': job['stage'],
        'stage_name': job['stage_name'],
        'error': job['error'],
        'has_pdf': 'pdf_path' in job['outputs'],
        'stages_complete': list(job['outputs'].keys()),
    }


@app.get('/jobs/{job_id}/output/{stage}')
def get_stage_output(job_id: str, stage: str):
    """Return the JSON output for a specific pipeline stage."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail='Job not found')
    outputs = jobs[job_id]['outputs']
    if stage not in outputs:
        raise HTTPException(status_code=404, detail=f'Stage {stage} not complete yet')
    return outputs[stage]


@app.get('/jobs/{job_id}/pdf')
def get_pdf(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail='Job not found')
    pdf_path = jobs[job_id]['outputs'].get('pdf_path')
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail='PDF not ready')
    return FileResponse(
        pdf_path,
        media_type='application/pdf',
        filename=f"{jobs[job_id]['part_name']}_program_sheet.pdf"
    )


@app.get('/jobs/{job_id}/step')
def get_step_file(job_id: str):
    """Serve the original STEP file for the 3D viewer."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail='Job not found')
    job_dir = JOBS_DIR / job_id
    step_files = list(job_dir.glob('*.step')) + list(job_dir.glob('*.stp'))
    if not step_files:
        raise HTTPException(status_code=404, detail='STEP file not found')
    return FileResponse(step_files[0], media_type='application/octet-stream')


@app.get('/jobs/{job_id}/fixture')
def get_fixture_spec(job_id: str):
    """Return the fixture_spec JSON for this job."""
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        return {'error': 'fixture spec not generated', 'setups': []}
    matches = list(job_dir.glob('*_fixture_spec.json'))
    if not matches:
        return {'error': 'fixture spec not generated', 'setups': []}
    with open(matches[0], encoding='utf-8') as f:
        return json.load(f)


@app.get('/jobs/{job_id}/jaw/{setup_index}/{side}')
def get_jaw_step(job_id: str, setup_index: int, side: str):
    """Serve a soft jaw STEP file. side = 'left' or 'right'."""
    if side.lower() not in ('left', 'right'):
        raise HTTPException(status_code=400, detail="side must be 'left' or 'right'")
    job_dir = JOBS_DIR / job_id
    pattern = f'*_setup{setup_index}_soft_jaw_{side.upper()}.step'
    matches = list(job_dir.glob(pattern))
    if not matches:
        raise HTTPException(status_code=404, detail=f'Jaw STEP not found: {pattern}')
    return FileResponse(matches[0], media_type='application/octet-stream')


_OCC_PYTHON = r'C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe'

_ASSEMBLE_SCRIPT = '''
import sys
from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCC.Core.IFSelect import IFSelect_RetDone

writer = STEPControl_Writer()

paths = sys.argv[2:]
for p in paths:
    if not p:
        continue
    r = STEPControl_Reader()
    if r.ReadFile(p) == IFSelect_RetDone:
        r.TransferRoots()
        writer.Transfer(r.OneShape(), STEPControl_AsIs)

writer.Write(sys.argv[1])
'''


@app.get('/jobs/{job_id}/fixture_assembly/{setup_index}')
def get_fixture_assembly(job_id: str, setup_index: int):
    """
    Merge part STEP + left jaw STEP + right jaw STEP into a single assembly
    STEP, generated via a subprocess call into the occ conda environment.
    Result is cached in the job folder.
    """
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail='Job not found')

    out_path = job_dir / f'fixture_assembly_{setup_index}.step'

    # Serve cached result if already built
    if out_path.exists():
        return FileResponse(str(out_path), media_type='application/octet-stream')

    # Find the part STEP (exclude jaw and assembly files)
    all_steps = [
        p for p in list(job_dir.glob('*.step')) + list(job_dir.glob('*.stp'))
        if 'soft_jaw' not in p.name and 'fixture_assembly' not in p.name
    ]
    if not all_steps:
        raise HTTPException(status_code=404, detail='Part STEP not found')
    part_step = str(all_steps[0])

    left_jaw_matches = list(job_dir.glob(f'*_setup{setup_index}_soft_jaw_LEFT.step'))
    right_jaw_matches = list(job_dir.glob(f'*_setup{setup_index}_soft_jaw_RIGHT.step'))

    # Auto-generate jaw STEPs if missing and fixture_spec says they're needed
    if not left_jaw_matches:
        fixture_spec_files = list(job_dir.glob('*_fixture_spec.json'))
        if fixture_spec_files:
            gen = subprocess.run(
                [_OCC_PYTHON, _SOFT_JAW_GENERATOR,
                 str(fixture_spec_files[0]), part_step],
                timeout=120,
                capture_output=True,
                text=True,
                cwd=str(job_dir),
            )
            # Refresh matches after generation attempt
            left_jaw_matches = list(job_dir.glob(f'*_setup{setup_index}_soft_jaw_LEFT.step'))
            right_jaw_matches = list(job_dir.glob(f'*_setup{setup_index}_soft_jaw_RIGHT.step'))

    left_jaw = str(left_jaw_matches[0]) if left_jaw_matches else ''
    right_jaw = str(right_jaw_matches[0]) if right_jaw_matches else ''

    # Write assembly script next to the output (avoids tempfile paths with spaces on Windows)
    script_path = job_dir / '_assemble_tmp.py'
    script_path.write_text(_ASSEMBLE_SCRIPT, encoding='utf-8')
    try:
        result = subprocess.run(
            [_OCC_PYTHON, str(script_path), str(out_path), part_step, left_jaw, right_jaw],
            timeout=60,
            capture_output=True,
            text=True,
        )
    finally:
        script_path.unlink(missing_ok=True)

    if result.returncode != 0 or not out_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f'Assembly generation failed: {result.stderr[-500:] if result.stderr else "unknown error"}'
        )

    return FileResponse(str(out_path), media_type='application/octet-stream')


# ── Feature map ──────────────────────────────────────────────────────────────

_INSPECTION_SECTION = {
    'through_hole': 'Holes', 'blind_hole': 'Holes', 'tapped_hole': 'Holes',
    'counterbore': 'Holes', 'countersink': 'Holes', 'large_bore': 'Holes',
    'pocket': 'Pockets', 'rectangular_pocket': 'Pockets', 'circular_pocket': 'Pockets',
    'slot': 'Slots', 'rectangular_slot': 'Slots',
    'boss': 'Bosses', 'cylindrical_boss': 'Bosses',
    'chamfer': 'Chamfers', 'fillet': 'Fillets',
    'planar_face': 'Faces', 'face': 'Faces',
}

@app.get('/jobs/{job_id}/faces')
def get_faces(job_id: str):
    """Return per-face feature data derived from the classified JSON."""
    job_dir = JOBS_DIR / job_id
    matches = list(job_dir.glob('*_classified.json'))
    if not matches:
        return {'faces': []}
    with open(matches[0], encoding='utf-8') as f:
        data = json.load(f)
    faces = []
    for cluster in data.get('clusters', []):
        fid = str(cluster.get('cluster_id', ''))
        ftype = cluster.get('feature_type', 'unknown')
        section = _INSPECTION_SECTION.get(ftype, 'Other')
        for fi in cluster.get('face_indices', []):
            faces.append({
                'feature_id': fid,
                'feature_type': ftype,
                'inspection_section': section,
                'face_index': fi,
                'centroid': None,
            })
    return {'faces': faces}


# ── Datums ───────────────────────────────────────────────────────────────────

@app.get('/jobs/{job_id}/datums')
def get_datums(job_id: str):
    job_dir = JOBS_DIR / job_id
    datum_file = job_dir / 'datums.json'
    if not datum_file.exists():
        return {'datums': []}
    with open(datum_file, encoding='utf-8') as f:
        return json.load(f)

@app.post('/jobs/{job_id}/datums')
async def save_datums(job_id: str, payload: dict):
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail='Job not found')
    datum_file = job_dir / 'datums.json'
    with open(datum_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    return {'ok': True}


# ── Tolerances ───────────────────────────────────────────────────────────────

@app.get('/jobs/{job_id}/tolerances')
def get_tolerances(job_id: str):
    job_dir = JOBS_DIR / job_id
    tol_file = job_dir / 'tolerances.json'
    if not tol_file.exists():
        return {}
    with open(tol_file, encoding='utf-8') as f:
        return json.load(f)

@app.post('/jobs/{job_id}/tolerances')
async def save_tolerances(job_id: str, payload: dict):
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail='Job not found')
    tol_file = job_dir / 'tolerances.json'
    with open(tol_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    return {'ok': True}


# ── Inspection template ─────────────────────────────────────────────────────
# NOTE: the frontend's InspectionTab.js has called GET /jobs/{id}/inspection
# since it was built, but no route implemented it — every "Download Template"
# click 404'd. This wires it to the two existing standalone scripts
# (datum_transform.py, inspection/template_generator.py) that were never
# connected to capp_service's per-job folder convention.

@app.get('/jobs/{job_id}/inspection')
def get_inspection_template(job_id: str):
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail='Job not found')

    datum_file = job_dir / 'datums.json'
    if not datum_file.exists():
        raise HTTPException(status_code=400, detail='Save datums first (Datum Tagger tab)')

    features_matches = list(job_dir.glob('*_classified.json'))
    if not features_matches:
        raise HTTPException(status_code=400, detail='Feature classification not complete yet')
    features_path = features_matches[0]

    datumed_path = job_dir / (features_path.stem + '_datumed.json')
    if not datumed_path.exists():
        result = subprocess.run(
            [sys.executable, _DATUM_TRANSFORM, str(features_path), str(datum_file)],
            cwd=str(job_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 or not datumed_path.exists():
            raise HTTPException(
                status_code=500,
                detail=f'Datum transform failed: {result.stderr[-500:] if result.stderr else "unknown error"}'
            )

    tol_file = job_dir / 'tolerances.json'
    params_matches = list(job_dir.glob('*_params.json'))

    output_path = job_dir / (features_path.stem.replace('_classified', '') + '_inspection_template.xlsx')
    cmd = [sys.executable, _INSPECTION_TEMPLATE_GENERATOR, str(datumed_path)]
    cmd.append(str(tol_file) if tol_file.exists() else '')
    if params_matches:
        cmd += ['--metadata', str(params_matches[0])]
    cmd += ['--output', str(output_path)]

    result = subprocess.run(cmd, cwd=str(job_dir), capture_output=True, text=True, timeout=60)
    if result.returncode != 0 or not output_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f'Inspection template generation failed: {result.stderr[-500:] if result.stderr else "unknown error"}'
        )

    try:
        job_manifest.register_artifact(job_dir, 'inspection_template', output_path.name)
        job_manifest.register_artifact(job_dir, 'features_datumed', datumed_path.name)
    except FileNotFoundError:
        pass

    return FileResponse(
        str(output_path),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        filename=output_path.name,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Investor-demo endpoints: DFM, quote, reply draft, CMM program, tracking.
# Logic lives in demo_modules/; contract documented in demo_modules/API.md.
# ══════════════════════════════════════════════════════════════════════════════

import threading
from typing import Literal, Optional
from pydantic import BaseModel

from demo_modules import v3_cache, dfm as demo_dfm, quote as demo_quote, reply as demo_reply
from demo_modules import cmm as demo_cmm, tracking as demo_tracking, part_data, step_geometry

_geometry_locks: dict = {}
_geometry_locks_guard = threading.Lock()


def _geometry_lock(job_id: str) -> threading.Lock:
    with _geometry_locks_guard:
        return _geometry_locks.setdefault(job_id, threading.Lock())


def _warm_geometry(job_id: str, job_dir: Path):
    try:
        steps = part_data.job_step_files(job_dir)
        if steps:
            with _geometry_lock(job_id):
                step_geometry.load_or_extract(job_dir, steps[0])
    except Exception:
        pass  # /cmm will surface the error when asked


def _start_demo_background(job_id: str, job_dir: Path):
    try:
        v3_cache.start(job_id, job_dir)
    except Exception:
        pass
    threading.Thread(target=_warm_geometry, args=(job_id, job_dir), daemon=True).start()


def _demo_job_dir(job_id: str) -> Path:
    job_dir = JOBS_DIR / job_id
    if not job_dir.is_dir() or not all(c.isalnum() or c == '-' for c in job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    return job_dir


def _part_name(job_id: str, job_dir: Path) -> str:
    if job_id in jobs:
        return jobs[job_id].get('part_name') or 'Part'
    m = job_manifest.load(job_dir) or {}
    return m.get('part_name') or 'Part'


def _v3_or_response(job_id: str, job_dir: Path):
    """(v3_dict, None) when ready, else (None, JSONResponse) for running/unavailable/failed."""
    state, payload = v3_cache.get(job_id, job_dir)
    if state == 'ready':
        return payload, None
    if state == 'running':
        return None, JSONResponse({'status': 'running', **payload})
    if state == 'unavailable':
        return None, JSONResponse(status_code=503, content={
            'status': 'unavailable', 'error': 'v3 analysis not available', **payload})
    return None, JSONResponse(status_code=500, content={
        'status': 'failed', 'error': 'v3 analysis failed', 'detail': payload.get('error')})


@app.get('/jobs/{job_id}/dfm')
def get_dfm(job_id: str, retry: bool = False):
    from demo_modules import dfm_geometry
    job_dir = _demo_job_dir(job_id)
    steps = part_data.job_step_files(job_dir)
    lock = _geometry_lock(job_id + ':dfm')

    def face_geometry():
        # face-level facts from the job's STEP, cached in <job>/dfm_geometry.json
        with lock:
            return dfm_geometry.load_or_extract(job_dir, steps[0])

    # warm the face-level geometry while v3 is still running (first call ~6 s on Motor Mount)
    if steps and not (job_dir / dfm_geometry.CACHE_NAME).exists() and not lock.locked():
        threading.Thread(target=lambda: face_geometry(), daemon=True).start()
    if retry:
        v3_cache.retry(job_id, job_dir)
    v3, resp = _v3_or_response(job_id, job_dir)
    if resp is not None:
        return resp
    geometry, geom_err = None, None
    if steps:
        try:
            geometry = face_geometry()
        except Exception as e:
            geom_err = f'{type(e).__name__}: {e}'
    out = {'status': 'ok', **demo_dfm.build(v3, geometry), 'v3_origin': v3.get('v3_origin'),
           'v3_runtime_s': v3.get('runtime_s')}
    if geom_err:
        out['geometry_error'] = geom_err
    return out


@app.get('/jobs/{job_id}/quote')
def get_quote(job_id: str, qty: int = 1, material: str = 'aluminium_6061'):
    job_dir = _demo_job_dir(job_id)
    if qty < 1 or qty > 100000:
        raise HTTPException(status_code=400, detail='qty must be between 1 and 100000')
    v3, resp = _v3_or_response(job_id, job_dir)
    if resp is not None:
        return resp
    if not (v3.get('plan') or {}).get('total_minutes'):
        return JSONResponse(status_code=422, content={
            'status': 'incomplete', 'error': 'v3 analysis has no machining plan (plan.total_minutes missing)'})
    return demo_quote.build(v3, job_dir, qty, material)


class ReplyDraftRequest(BaseModel):
    client_comment: str
    # Ignored and optional: one client comment can raise several topics, the draft answers each in turn.
    topic: Optional[str] = None
    qty: Optional[int] = None
    material: Optional[str] = 'aluminium_6061'


@app.post('/jobs/{job_id}/reply-draft')
def post_reply_draft(job_id: str, body: ReplyDraftRequest):
    job_dir = _demo_job_dir(job_id)
    if not body.client_comment.strip():
        raise HTTPException(status_code=400, detail='client_comment is empty')
    part_dir = part_data.find_part_dir(job_dir)

    state, v3 = v3_cache.get(job_id, job_dir)
    quote = dfm = None
    if state == 'ready':
        dfm = demo_dfm.build(v3)
        if (v3.get('plan') or {}).get('total_minutes'):
            qty = body.qty or 1
            quote = demo_quote.build(v3, job_dir, qty, body.material or 'aluminium_6061')
    tolerances = part_data.load_inspection_characteristics(part_dir)

    facts = demo_reply.collect_facts(body.topic, quote, dfm, tolerances)
    if not facts:
        return JSONResponse(status_code=409, content={
            'status': 'no_facts', 'error': 'No quote, DFM or drawing tolerances available to ground a reply on'})
    try:
        return demo_reply.draft(body.client_comment, body.topic, _part_name(job_id, job_dir), facts)
    except demo_reply.ReplyError as e:
        return JSONResponse(status_code=e.status, content={'error': e.message, 'grounded_on': facts})


@app.get('/jobs/{job_id}/cmm')
def get_cmm(job_id: str):
    job_dir = _demo_job_dir(job_id)
    try:
        with _geometry_lock(job_id):
            return demo_cmm.build(job_dir, _part_name(job_id, job_dir))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'CMM program generation failed: {type(e).__name__}: {e}')


@app.get('/jobs/{job_id}/tracking')
def get_tracking(job_id: str):
    job_dir = _demo_job_dir(job_id)
    result = demo_tracking.build(job_dir)
    if result.get('available'):
        state, v3 = v3_cache.get(job_id, job_dir)
        if state == 'ready' and (v3.get('plan') or {}).get('total_minutes'):
            cyc = demo_quote.cycle_minutes(v3)
            result['summary']['v3_plan_minutes'] = cyc['total_minutes']          # quoted cycle (ATC tool changes)
            result['summary']['v3_raw_total_minutes'] = cyc['v3_total_minutes']  # v3's own, 15 min/manual change
    return result


# ── Program (v3 plan + live PowerMill run) and production history ──────────
from demo_modules import program as demo_program, production_history as demo_history


class ProgramApproveRequest(BaseModel):
    by: str


@app.get('/jobs/{job_id}/program')
def get_program(job_id: str):
    job_dir = _demo_job_dir(job_id)
    state, v3 = v3_cache.get(job_id, job_dir)
    return demo_program.build(job_dir, state, v3)


@app.get('/jobs/{job_id}/program/image/{name:path}')
def get_program_image(job_id: str, name: str):
    job_dir = _demo_job_dir(job_id)
    p = demo_program.image_path(demo_program.part_key_for_job(job_dir), name)
    if p is None:
        raise HTTPException(status_code=404, detail='Image not found')
    return FileResponse(str(p))


@app.post('/jobs/{job_id}/program/approve')
def post_program_approve(job_id: str, body: ProgramApproveRequest):
    job_dir = _demo_job_dir(job_id)
    if not body.by.strip():
        raise HTTPException(status_code=400, detail='by is empty')
    return {'status': 'ok', 'approved': demo_program.approve(job_dir, body.by)}


@app.get('/parts/{part_key}/production-history')
def get_part_production_history(part_key: str):
    return demo_history.build_for_key(part_key)


@app.get('/jobs/{job_id}/production-history')
def get_job_production_history(job_id: str):
    job_dir = _demo_job_dir(job_id)
    return demo_history.build(part_data.find_part_dir(job_dir), _part_name(job_id, job_dir))


def _warm_demo_caches():
    """Background warm-up so the first /program, /production-history, /tracking and /quote
    of the demo parts are served from the in-process file caches (keyed by file mtimes)."""
    import time as _t
    t0 = _t.time()
    for key in sorted(set(demo_program.LIVE_RUNS) | set(demo_history.EXTERNAL_BATCHES)):
        try:
            demo_program.live_program(key)
            pd = demo_history.find_part_dir_by_key(key)
            demo_history.build(pd, key)                        # .tap parses, inspection xlsx, G: drive MPFs
            part_data.load_inspection_characteristics(pd)     # /tracking QC, /reply-draft
            part_data.load_previous_quote(pd)                 # /quote
            if pd is not None:
                part_data.shop_cycle_references(pd, demo_tracking._cl())
        except Exception as e:
            print(f'[warm] {key}: {type(e).__name__}: {e}', flush=True)
    print(f'[warm] demo caches ready in {_t.time() - t0:.1f}s', flush=True)


threading.Thread(target=_warm_demo_caches, daemon=True, name='warm-demo-caches').start()


# ── Rohit's v3 console: start on demand for the /proto "Open v3 console" button ──────────────────
from demo_modules import v3_console as demo_v3_console


@app.post('/v3-console/ensure')
def v3_console_ensure():
    """Launch the v3 console (ui/server.py, port 8765) if it isn't running; return its URL."""
    if demo_v3_console.disabled():   # V3_DISABLED=1: server mode, v3 is not installed here
        return JSONResponse(status_code=501, content={
            'status': 'unavailable',
            'error': 'The v3 console is not available on this environment (V3_DISABLED=1).'})
    return demo_v3_console.ensure_running()


# ── Planner console runs: read them on the planning laptop, publish one for the shared app ───────
import re as _re
from fastapi import Request
from demo_modules import v3_runs as demo_v3_runs

_PNA_ORIGIN = _re.compile(r'^(https://dev\.shiaanx\.com|https?://(localhost|127\.0\.0\.1)(:\d+)?)$')


@app.middleware('http')
async def _private_network_access(request: Request, call_next):
    """Chrome's Private Network Access: a public https page (dev.shiaanx.com) calling this laptop
    server preflights with Access-Control-Request-Private-Network: true and needs it echoed back.
    CORSMiddleware does not do that, so add it for the allowed origins only."""
    response = await call_next(request)
    if (request.method == 'OPTIONS'
            and request.headers.get('access-control-request-private-network', '').lower() == 'true'
            and _PNA_ORIGIN.match(request.headers.get('origin', ''))):
        response.headers['Access-Control-Allow-Private-Network'] = 'true'
    return response


def _runs_unavailable():
    return JSONResponse(status_code=501, content={'status': 'unavailable', 'error': demo_v3_runs.UNAVAILABLE_MSG})


@app.get('/v3/runs')
def get_v3_runs(limit: int = 30):
    """Recent planner console runs on this computer, newest first."""
    if demo_v3_runs.disabled():
        return _runs_unavailable()
    return {'status': 'ok', 'runs': demo_v3_runs.list_runs(max(1, min(limit, 100)))}


@app.get('/v3/runs/{name}/summary')
def get_v3_run_summary(name: str):
    """The program summary (live_program shape) for one planner run, read-only."""
    if demo_v3_runs.disabled():
        return _runs_unavailable()
    if demo_v3_runs.run_dir(name) is None:
        raise HTTPException(status_code=404, detail='Planner run not found')
    live, notes = demo_v3_runs.summarize_run(name)
    return {'status': 'ok' if live else 'empty', 'run': name, 'summary': live, 'notes': notes}


@app.post('/jobs/{job_id}/program/publish')
async def post_program_publish(job_id: str, request: Request):
    """Store a planner run summary for this job's part ({summary, published_by, run_name})."""
    job_dir = _demo_job_dir(job_id)
    raw = await request.body()
    if len(raw) > demo_v3_runs.MAX_PUBLISH_BYTES:
        raise HTTPException(status_code=413, detail='Summary is larger than 2 MB')
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail='Body is not valid JSON')
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail='Body must be an object')
    key = demo_program.part_key_for_job(job_dir)
    try:
        rec = demo_v3_runs.publish(key, body.get('summary'), body.get('run_name'), body.get('published_by'))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {'status': 'ok', 'published': rec}


@app.get('/parts/{part_key}/published-run')
def get_part_published_run(part_key: str):
    rec = demo_v3_runs.load_published(part_key)
    if rec is None:
        return {'status': 'none', 'published': None}
    return {'status': 'ok', 'published': {k: rec.get(k) for k in ('part_key', 'run_name', 'published_by', 'published_at')},
            'label': demo_v3_runs.source_label(rec)}


# ── Client quote PDF (editable quote -> Finalize) ──────────────────────────────────────────────────
from demo_modules import quote_pdf as demo_quote_pdf


class QuoteEdits(BaseModel):
    unit_price_inr: Optional[float] = None
    total_inr: Optional[float] = None
    lead_days: Optional[int] = None
    validity_days: Optional[int] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None


class QuotePdfRequest(BaseModel):
    customer: Optional[str] = None
    enquiry_number: Optional[str] = None
    part_name: Optional[str] = None
    qty: int = 1
    material: Optional[str] = 'aluminium_6061'
    edits: Optional[QuoteEdits] = None
    prepared_by: Optional[str] = None
    dfm_snapshot_png_base64: Optional[str] = None


@app.post('/jobs/{job_id}/quote-pdf')
def post_quote_pdf(job_id: str, body: QuotePdfRequest):
    from fastapi.responses import Response
    from demo_modules import dfm_geometry
    job_dir = _demo_job_dir(job_id)
    if body.qty < 1 or body.qty > 100000:
        raise HTTPException(status_code=400, detail='qty must be between 1 and 100000')
    v3, resp = _v3_or_response(job_id, job_dir)
    if resp is not None:
        return JSONResponse(status_code=409, content={'status': 'not_ready', 'error': 'The part analysis is not finished yet.'})
    if not (v3.get('plan') or {}).get('total_minutes'):
        return JSONResponse(status_code=422, content={'status': 'incomplete', 'error': 'The part has no machining plan yet.'})
    quote = demo_quote.build(v3, job_dir, body.qty, body.material or 'aluminium_6061')
    geometry = None
    steps = part_data.job_step_files(job_dir)
    if steps:
        try:
            with _geometry_lock(job_id + ':dfm'):
                geometry = dfm_geometry.load_or_extract(job_dir, steps[0])
        except Exception:
            geometry = None
    dfm = demo_dfm.build(v3, geometry)
    edits = body.edits.dict() if body.edits else {}
    pdf = demo_quote_pdf.build_pdf(
        customer=body.customer, enquiry_number=body.enquiry_number, part_name=body.part_name or _part_name(job_id, job_dir),
        qty=body.qty, material=body.material, edits=edits, prepared_by=body.prepared_by, quote=quote, dfm=dfm,
        snapshot_png=demo_quote_pdf.decode_snapshot(body.dfm_snapshot_png_base64))
    return Response(content=pdf, media_type='application/pdf',
                    headers={'Content-Disposition': 'attachment; filename="quotation.pdf"'})


# ── Prepared QC sheet for a part (one-click "Use earlier results" on the order page) ───────────────
from demo_modules import qc_sheet as demo_qc_sheet


@app.get('/parts/{part_key}/has-qc-sheet')
def get_part_has_qc_sheet(part_key: str):
    p = demo_qc_sheet.find(part_key)
    return {'available': p is not None, 'file_name': p.name if p else None}


@app.get('/parts/{part_key}/qc-sheet')
def get_part_qc_sheet(part_key: str):
    p = demo_qc_sheet.find(part_key)
    if p is None:
        return JSONResponse(status_code=404, content={'status': 'none', 'error': 'No QC sheet is prepared for this part.'})
    return FileResponse(str(p), filename=p.name,
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ── Open the generated program in PowerMill (planning laptop only) ───────────────────────────────
from demo_modules import powermill_ctl as demo_powermill


def _pm_call(fn, *args, **kwargs):
    if demo_v3_runs.disabled():
        return JSONResponse(status_code=501, content={
            'ok': False, 'status': 'unavailable', 'error': 'PowerMill is only available on the planning laptop.'})
    try:
        return fn(*args, **kwargs)
    except demo_powermill.PmError as e:
        return JSONResponse(status_code=e.http, content=e.payload())
    except Exception as e:   # never leak a traceback to the page
        return JSONResponse(status_code=500, content={'ok': False, 'status': 'error', 'error': f'{type(e).__name__}: {str(e)[:200]}'})


class PowerMillOpen(BaseModel):
    run_name: Optional[str] = None


class PowerMillToolpath(BaseModel):
    name: str


@app.get('/v3/powermill/status')
def get_powermill_status():
    return _pm_call(demo_powermill.status)


@app.get('/v3/powermill/toolpaths')
def get_powermill_toolpaths():
    return _pm_call(demo_powermill.list_toolpaths)


@app.post('/v3/powermill/open-program')
def post_powermill_open(body: Optional[PowerMillOpen] = None):
    return _pm_call(demo_powermill.open_program, body.run_name if body else None)


@app.post('/v3/powermill/show-toolpath')
def post_powermill_show(body: PowerMillToolpath):
    return _pm_call(demo_powermill.show_toolpath, body.name)


@app.post('/v3/powermill/recalculate')
def post_powermill_recalculate(body: PowerMillToolpath):
    return _pm_call(demo_powermill.recalculate, body.name)
