"""
Parse Siemens MPF G-code files to extract tool change sequences for the Motor Mount audit.
"""
import re
import json
import os

CAM_DIR = r"G:\My Drive\Closed Loop\Motor Mount\CAM files"

MPF_FILES = [
    ("MOTOR_MOUNT_1_SETUP..MPF",        1),
    ("MOTOR_MOUNT_2_SETUP..MPF",        2),
    ("MOTOR_MOUNT_3_FINISH_SETUP..MPF", 3),
    ("MOTOR_MOUNT_4_SETUP..MPF",        4),
]

def extract_tools_from_mpf(filepath):
    """
    Siemens Sinumerik 828D MPF format:
      T1; - T1 END MILL D10   <- tool load line (T<n>; comment)
      M6                       <- tool change execute
      T2                       <- pre-select NEXT tool
      MSG("op name = time")   <- operation label
    """
    tool_calls = []
    spindle_speeds = []
    feed_rates = []

    with open(filepath, "r", errors="replace") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Tool load: T<n>; - description
        m = re.match(r'^(T(\d+))\s*;(.*)$', line)
        if m:
            tool_num = int(m.group(2))
            tool_desc = m.group(3).strip()
            # next non-empty line should be M6
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip().upper().startswith("M6"):
                # look for MSG line a few lines after M6
                op_name = ""
                for k in range(j+1, min(j+5, len(lines))):
                    msg_m = re.search(r'MSG\("([^"]+)"\)', lines[k])
                    if msg_m:
                        op_name = msg_m.group(1).strip()
                        break
                tool_calls.append({
                    "line": i+1,
                    "tool_number": tool_num,
                    "tool_description": tool_desc,
                    "operation_name": op_name,
                    "raw": line,
                })

        # Spindle speed (S<n> M3)
        if re.search(r'\bS(\d+)\b', line) and ("M3" in line or "M03" in line):
            s_m = re.search(r'\bS(\d+)\b', line)
            if s_m:
                spindle_speeds.append(int(s_m.group(1)))

        # Feed rate
        f_m = re.search(r'\bF(\d+\.?\d*)\b', line)
        if f_m:
            feed_rates.append(float(f_m.group(1)))

        i += 1

    return {
        "tool_calls": tool_calls,
        "unique_spindle_speeds": sorted(set(spindle_speeds)),
        "unique_feed_rates": sorted(set(feed_rates))[:20],
        "total_lines": len(lines),
    }


def main():
    results = {"part": "Motor Mount", "setups": []}

    for filename, setup_num in MPF_FILES:
        filepath = os.path.join(CAM_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  MISSING: {filepath}")
            results["setups"].append({
                "setup_number": setup_num,
                "file": filename,
                "error": "FILE NOT FOUND"
            })
            continue

        print(f"Parsing Setup {setup_num}: {filename}")
        data = extract_tools_from_mpf(filepath)
        print(f"  Tool calls found: {len(data['tool_calls'])}")
        print(f"  Spindle speeds: {data['unique_spindle_speeds']}")
        print(f"  Total lines: {data['total_lines']}")
        for tc in data["tool_calls"]:
            print(f"    Line {tc['line']}: {tc['raw']}")

        results["setups"].append({
            "setup_number": setup_num,
            "file": filename,
            "total_lines": data["total_lines"],
            "tool_calls": data["tool_calls"],
            "tool_call_count": len(data["tool_calls"]),
            "unique_spindle_speeds": data["unique_spindle_speeds"],
            "unique_feed_rates": data["unique_feed_rates"][:20],  # cap for readability
        })

    out_path = os.path.join(os.path.dirname(__file__), "gcode_tool_summary.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
