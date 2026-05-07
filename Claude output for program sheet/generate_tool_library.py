"""
generate_tool_library.py
Converts 7a. tool_database.json → shiaanx_tools.hsmlib
Import the .hsmlib into Fusion 360 via: Manage → Tool Library → Local → Import Tools

Usage:
    conda run -n occ python "Claude output for program sheet/generate_tool_library.py"
"""

import json
import math
import uuid
from pathlib import Path

BASE = Path(__file__).parent
DB_PATH  = BASE / '7a. tool_database.json'
OUT_PATH = BASE / 'shiaanx_tools.hsmlib'

TYPE_MAP = {
    'spot_drill':      'center drill',
    'center_drill':    'center drill',
    'twist_drill':     'drill',
    'pilot_drill':     'drill',
    'core_drill':      'drill',
    'end_mill':        'flat end mill',
    'contour_mill':    'flat end mill',
    'pocket_mill':     'flat end mill',
    'circular_interp': 'flat end mill',
    'face_mill':       'face mill',
    'chamfer_mill':    'chamfer mill',
    'slot_mill':       'slot mill',
    'tap_rh':          'tap right hand',
    'boring_bar':      'boring bar',
}

DRILL_OPS = {'spot_drill', 'center_drill', 'twist_drill', 'pilot_drill',
             'core_drill', 'tap_rh', 'boring_bar'}


def fusion_type(op: str) -> str:
    return TYPE_MAP.get(op, 'flat end mill')


def ct_field(op: str) -> str:
    return 'drill' if op in DRILL_OPS else 'mill'


def make_presets(tool: dict) -> list:
    """Build Fusion-format presets from material_params."""
    presets = []
    params = tool.get('material_params', {})
    dia    = tool.get('diameter_mm', 10.0)
    op     = tool.get('operation', '')
    if isinstance(op, list):
        op = op[0]
    if op == 'face_mill':
        flutes = tool.get('insert_count', tool.get('inserts', 4))
    else:
        flutes = tool.get('flutes', 2)

    for mat_key, mp in params.items():
        if 'alumin' in mat_key.lower():
            mat_label    = 'Aluminum'
            mat_category = 'metal'
            mat_query    = 'Aluminum'
        else:
            mat_label    = mat_key.replace('_', ' ').title()
            mat_category = 'metal'
            mat_query    = mat_label

        material_obj = {'category': mat_category, 'query': mat_query, 'use-hardness': False}

        def _preset(name, vc, fz, suffix=''):
            rpm  = (vc * 1000) / (math.pi * dia) if dia > 0 else 0
            vf   = rpm * fz * flutes
            vf_p = vf * 0.33
            return {
                'description': f'ShiaanX {mat_label} {suffix}'.strip(),
                'f_n':         round(fz, 5),
                'f_z':         round(fz, 5),
                'guid':        str(uuid.uuid4()),
                'material':    material_obj,
                'n':           round(rpm, 1),
                'n_ramp':      round(rpm, 1),
                'name':        name,
                'ramp-angle':  2.0,
                'tool-coolant': 'flood',
                'use-stepdown': False,
                'use-stepover': False,
                'v_c':         round(vc, 2),
                'v_f':         round(vf, 1),
                'v_f_leadIn':  round(vf, 1),
                'v_f_leadOut': round(vf, 1),
                'v_f_plunge':  round(vf_p, 1),
                'v_f_ramp':    round(vf, 1),
                'v_f_transition': round(vf, 1),
            }

        vc_r = mp.get('Vc_rough_mmin') or mp.get('Vc_mmin') or 200
        fz_r = mp.get('fz_rough_mm') or mp.get('feed_per_rev_mm') or 0.05
        presets.append(_preset(f'{mat_label} - Roughing', vc_r, fz_r, 'Roughing'))

        vc_f = mp.get('Vc_finish_mmin')
        fz_f = mp.get('fz_finish_mm')
        if vc_f and fz_f:
            presets.append(_preset(f'{mat_label} - Finishing', vc_f, fz_f, 'Finishing'))

    return presets


def convert(tool: dict, tool_number: int) -> dict:
    op = tool.get('operation', 'end_mill')
    if isinstance(op, list):
        op = op[0]
    dia    = tool.get('diameter_mm', 10.0)
    flutes = tool.get('flutes', 2)
    if op == 'face_mill':
        flutes = tool.get('insert_count', tool.get('inserts', 4))

    if op == 'face_mill':
        shank_dia = 22.0  # arbor mount
        geometry = {
            'CSP':              False,
            'DC':               dia,
            'HAND':             True,
            'LB':               round(dia * 0.6, 3),   # body depth ~60% of dia
            'LCF':              round(dia * 0.12, 3),  # insert engagement depth
            'NOF':              float(flutes),
            'OAL':              round(dia * 0.8, 3),   # realistic OAL for face mill
            'SFDM':             shank_dia,
            'shoulder-diameter': dia,
            'shoulder-length':  round(dia * 0.12, 3),
        }
    else:
        geometry = {
            'CSP':              False,
            'DC':               dia,
            'HAND':             True,
            'LB':               round(dia * 4.5, 3),
            'LCF':              round(dia * 3.5, 3),
            'NOF':              float(flutes),
            'OAL':              round(dia * 10, 3),
            'SFDM':             dia,
            'shoulder-diameter': dia,
            'shoulder-length':  round(dia * 3.5, 3),
        }
    if op in ('twist_drill', 'pilot_drill', 'core_drill'):
        geometry['TA'] = float(tool.get('point_angle_deg', 118))
    if op in ('spot_drill', 'center_drill'):
        geometry['TA'] = float(tool.get('point_angle_deg', 90))

    return {
        'BMC':          'carbide',
        'CT':           ct_field(op),
        'description':  'ShiaanX: ' + tool.get('description', tool.get('tool_id', '')),
        'geometry':     geometry,
        'guid':         str(uuid.uuid4()),
        'post-process': {
            'break-control':      False,
            'comment':            tool.get('tool_id', ''),
            'diameter-offset':    float(tool_number),
            'length-offset':      float(tool_number),
            'live':               True,
            'manual-tool-change': False,
            'number':             float(tool_number),
            'turret':             0.0,
        },
        'product-id':   tool.get('tool_id', ''),
        'product-link': '',
        'start-values': {
            'presets': make_presets(tool)
        },
        'type':   fusion_type(op),
        'unit':   'millimeters',
        'vendor': tool.get('manufacturer', 'Sandvik Coromant'),
    }


def main():
    with open(DB_PATH, encoding='utf-8') as f:
        db = json.load(f)

    tools = db.get('tools', [])
    data  = []
    num   = 1
    for tool in tools:
        if '_section' in tool and 'tool_id' not in tool:
            continue
        if 'tool_id' not in tool:
            continue
        data.append(convert(tool, num))
        num += 1

    # version must be 36 to match Fusion's current schema version
    out = {'data': data, 'version': 36}
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)

    print(f"Written {len(data)} tools to {OUT_PATH}")
    print("Import into Fusion 360: Manage > Tool Library > Local > Library > Import Tools")


if __name__ == '__main__':
    main()
