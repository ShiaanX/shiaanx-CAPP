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

from runner import start_pipeline

app = FastAPI(title='ShiaanX CAPP Service')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

JOBS_DIR = Path(__file__).parent / 'jobs'
JOBS_DIR.mkdir(exist_ok=True)

# In-memory job store: { job_id: { status, stage, stage_name, outputs, error } }
jobs: dict = {}


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

    start_pipeline(job_id, str(step_path), material, part_name, jobs)

    return {'job_id': job_id}


@app.get('/jobs/{job_id}')
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail='Job not found')
    job = jobs[job_id]
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
    left_jaw = str(left_jaw_matches[0]) if left_jaw_matches else ''
    right_jaw = str(right_jaw_matches[0]) if right_jaw_matches else ''

    # Write and run the assembly script in the occ env
    tmp = tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w', encoding='utf-8')
    tmp.write(_ASSEMBLE_SCRIPT)
    tmp.close()
    try:
        result = subprocess.run(
            [_OCC_PYTHON, tmp.name, str(out_path), part_step, left_jaw, right_jaw],
            timeout=60,
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(tmp.name)

    if result.returncode != 0 or not out_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f'Assembly generation failed: {result.stderr[-500:] if result.stderr else "unknown error"}'
        )

    return FileResponse(str(out_path), media_type='application/octet-stream')
