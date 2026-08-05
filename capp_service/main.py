import uuid
import os
import io
import importlib.util
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import aiofiles

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

# Load 9. program_sheet.py for on-demand PDF generation
PIPELINE_DIR = Path(__file__).parent.parent / 'Claude output for program sheet'
program_sheet_script = PIPELINE_DIR / '9. program_sheet.py'
spec = importlib.util.spec_from_file_location('program_sheet', str(program_sheet_script))
ps_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps_module)

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


from fastapi.concurrency import run_in_threadpool

@app.post('/pdf/generate')
async def generate_pdf_on_demand(request: Request):
    """
    On-demand PDF program sheet generation directly from JSON data payload.
    Never saves PDF files to disk.
    """
    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail='Invalid or empty JSON body')
        
        # If payload is full state, extract pipeline_output or params if present
        params_data = data.get('pipeline_output') or data.get('params') or data
        part_name = data.get('partName') or data.get('part_name') or 'Part'
        
        def _build_pdf():
            buf = io.BytesIO()
            ps_module.generate_program_sheet(
                params_data=params_data,
                output_path=buf,
                part_name=part_name,
                programmer='CNC-AI'
            )
            return buf.getvalue()

        pdf_bytes = await run_in_threadpool(_build_pdf)
        
        return Response(
            content=pdf_bytes,
            media_type='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{part_name}_program_sheet.pdf"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to generate PDF: {str(e)}')
