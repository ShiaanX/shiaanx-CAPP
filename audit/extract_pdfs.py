"""Extract text from Motor Mount PDF setup sheets using PyMuPDF."""
import fitz
import json
import os

pdfs = {
    "setup_1": r"G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_1_SETUP_SHEET.pdf",
    "setup_2": r"G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_2_SETUP_SHEET.pdf",
    "setup_3": r"G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_3_FINISH_SETUP_SHEET.pdf",
    "setup_4": r"G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_4_SETUP_SHEET.pdf",
}

for key, path in pdfs.items():
    print(f"\n{'='*60}")
    print(f"=== {key}: {os.path.basename(path)} ===")
    print('='*60)
    doc = fitz.open(path)
    for page_num, page in enumerate(doc, 1):
        text = page.get_text()
        print(f"--- Page {page_num} ---")
        print(text)
    doc.close()
