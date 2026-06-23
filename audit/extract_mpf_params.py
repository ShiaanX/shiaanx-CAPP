"""Extract feeds and speeds from Motor Mount MPF G-code files."""
import re
import json
import os

mpf_files = {
    "setup_1": r"G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_1_SETUP..MPF",
    "setup_2": r"G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_2_SETUP..MPF",
    "setup_3": r"G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_3_FINISH_SETUP..MPF",
    "setup_4": r"G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_4_SETUP..MPF",
}

# Tool descriptions from headers
tool_descriptions = {
    "setup_1": {
        "T1": "END MILL D10.0",
        "T2": "CENTER DRILL D2.0",
        "T3": "DRILL D2.5",
        "T4": "DRILL D3.2",
        "T5": "END MILL D8.0",
        "T6": "END MILL D3.0",
        "T7": "END MILL D4.0",
        "T8": "BULL NOSE MILL D8.0 R1",
        "T9": "BALL NOSE D5.0",
        "T10": "CHAMFER MILL D10.0",
    },
    "setup_2": {
        "T1": "END MILL D10.0",
        "T11": "DRILL D3.0",
        "T7": "END MILL D4.0",
        "T8": "BULL NOSE MILL D8.0 R1",
        "T9": "BALL NOSE D5.0",
        "T12": "BALL NOSE D3.0",
    },
    "setup_3": {
        "T1": "END MILL D10.0",
        "T9": "BALL NOSE D5.0",
    },
    "setup_4": {
        "T13": "END MILL D10.0",
        "T10": "CHAMFER MILL D10.0",
        "T14": "END MILL D3.0",
    },
}

all_results = {}

for setup_key, filepath in mpf_files.items():
    params = []
    current_tool = None
    current_speed = None
    seen_entries = set()  # avoid duplicates

    with open(filepath, 'r', errors='replace') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Tool change: "T1;" or "T1 ;" pattern (not comment lines)
        tool_match = re.match(r'^T(\d+)\s*;', line)
        if tool_match and not line.startswith(';'):
            current_tool = f"T{tool_match.group(1)}"

        # Speed: S in a G00 line with M3/M03
        if re.search(r'S(\d+)\s+M0?3', line):
            spd_match = re.search(r'S(\d+)', line)
            if spd_match:
                current_speed = int(spd_match.group(1))

        # Feed: F in motion lines (G01/G02/G03) - collect the first F for this tool/speed combo
        if current_tool and current_speed and re.search(r'[GF]\d', line):
            f_match = re.search(r'\bF(\d+\.?\d*)\b', line)
            if f_match and not line.startswith(';'):
                feed = float(f_match.group(1))
                entry_key = (current_tool, current_speed, feed)
                if entry_key not in seen_entries:
                    seen_entries.add(entry_key)
                    tool_desc = tool_descriptions.get(setup_key, {}).get(current_tool, "unknown")
                    params.append({
                        "tool": current_tool,
                        "tool_description": tool_desc,
                        "speed_rpm": current_speed,
                        "feed_mmpm": feed,
                    })
        i += 1

    all_results[setup_key] = params

# Save
os.makedirs("audit", exist_ok=True)
with open("audit/motor_mount_actual_params.json", "w") as f:
    json.dump(all_results, f, indent=2)

print("Saved audit/motor_mount_actual_params.json")
for key, data in all_results.items():
    print(f"\n{key}: {len(data)} parameter entries")
    # Show unique tool/speed combos
    seen = set()
    for p in data:
        k = (p["tool"], p["tool_description"], p["speed_rpm"])
        if k not in seen:
            seen.add(k)
            print(f"  {p['tool']} ({p['tool_description']}) S={p['speed_rpm']}")
