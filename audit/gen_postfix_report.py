"""
Generate accuracy_breakdown_motormount_postfix.txt from the postfix pipeline outputs.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from compare_motor_mount import GT_FEATURES, generate_report
import json
from pathlib import Path

AUDIT = Path(__file__).parent

def main():
    with open(AUDIT / "classified_motormount_postfix.json") as f:
        classified = json.load(f)
    clusters = classified["clusters"]

    with open(AUDIT / "processes_motormount_postfix.json") as f:
        processes_data = json.load(f)
    processes = processes_data["clusters"]

    out_path = AUDIT / "accuracy_breakdown_motormount_postfix.txt"
    total_correct, total_expected = generate_report(
        clusters, processes, out_path, suffix=" [POST-FIX]"
    )
    print(f"\nPost-fix accuracy: {100*total_correct/max(1,total_expected):.1f}% ({total_correct}/{total_expected})")

if __name__ == "__main__":
    main()
