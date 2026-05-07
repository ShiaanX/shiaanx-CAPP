"""
agent_loop.py — Thin autonomous improvement agent for CAD feature classification.

Loop:
  1. Diagnose  — find weakest feature classes by F1
  2. Search    — find relevant datasets on Kaggle + GitHub
  3. [GEMINI]  — decide which dataset to try (LLM call #1)
  4. Download  — pull chosen dataset
  5. Retrain   — train new RF candidate
  6. [GEMINI]  — decide whether to promote or investigate further (LLM call #2)
  7. Promote   — replace production model if accuracy improves
  8. Sleep and repeat

Set env vars before running:
  GEMINI_API_KEY      — your Google AI Studio API key (free at aistudio.google.com)
  KAGGLE_USERNAME     — your Kaggle username (or use ~/.kaggle/kaggle.json)
  KAGGLE_KEY          — your Kaggle API key

Usage:
  conda run -n occ python "Claude output for program sheet/Autonomous Agent/agent_loop.py"
  conda run -n occ python "Claude output for program sheet/Autonomous Agent/agent_loop.py" --once
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from google import genai

# Add parent dir so we can import sibling agent modules
AGENT_DIR = Path(__file__).parent
sys.path.insert(0, str(AGENT_DIR))

import agent_diagnose
import agent_search
import agent_retrain
import agent_promote

LOG_DIR = AGENT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

GEMINI_MODEL   = "gemini-2.5-flash-lite"
LOOP_SLEEP_SEC = 3600  # 1 hour between full cycles


# ---------------------------------------------------------------------------
# Gemini decision helpers — only two LLM calls per cycle
# ---------------------------------------------------------------------------

def _gemini_pick_dataset(diagnosis: dict, search_results: dict, model) -> dict | None:
    """
    Ask Gemini which dataset to try first.
    Returns the chosen dataset dict, or None if nothing looks useful.
    """
    weak = [f"{c['class']} (F1={c['f1']:.3f})" for c in diagnosis["weakest_classes"]]
    kaggle = search_results.get("kaggle", [])
    github = search_results.get("github", [])

    prompt = f"""You are helping an autonomous ML improvement agent for a CNC machining feature classifier (25 classes: holes, pockets, slots, chamfers, bosses, faces, etc. — Random Forest on geometric face features).

Current model accuracy: {diagnosis['overall_accuracy']*100:.1f}%

Weakest feature classes (by F1 score):
{chr(10).join(f'  - {w}' for w in weak)}

Kaggle datasets found:
{json.dumps(kaggle, indent=2)}

GitHub repositories found:
{json.dumps(github, indent=2)}

Task: Pick the single most promising dataset to try next. A good dataset should:
- Contain STEP, IGES, or B-Rep files with any form of geometric/feature annotations
- Cover mechanical or machined parts (not purely organic shapes)
- Be reasonably sized (< 5 GB)
- Likely provide training signal for one of the weak classes above
- Does NOT need to be MFCAD++ specifically — any labeled CAD geometry dataset is useful

Reply in valid JSON only, no markdown:
{{
  "chosen": {{<the full dataset dict you selected>}} or null if nothing is suitable,
  "reason": "<one sentence why>",
  "expected_impact": "<which weak class this most likely helps>"
}}"""

    response = model.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        result = json.loads(text)
        print(f"[gemini] Chose: {result.get('chosen', {}).get('title', 'None') if result.get('chosen') else 'None'}")
        print(f"[gemini] Reason: {result.get('reason', '')}")
        return result.get("chosen")
    except json.JSONDecodeError:
        print(f"[gemini] Could not parse response: {text[:200]}")
        return None


def _gemini_evaluate_result(diagnosis_before: dict, retrain_result: dict, promote_result: dict, model) -> str:
    """
    Ask Gemini to interpret the cycle outcome and suggest next action.
    Returns one of: 'continue' | 'focus_features' | 'stop'
    """
    prompt = f"""You are reviewing a completed improvement cycle for a CNC machining feature classifier.

Before this cycle:
  - Accuracy: {diagnosis_before['overall_accuracy']*100:.1f}%
  - Weakest class: {diagnosis_before['weakest_classes'][0]['class']} (F1={diagnosis_before['weakest_classes'][0]['f1']:.3f})

After retraining:
  - New accuracy: {retrain_result['accuracy']*100:.2f}%
  - Promoted to production: {promote_result['promoted']}
  - Outcome: {promote_result['reason']}

Recommend next action:
- "continue" — keep searching for more datasets
- "focus_features" — data isn't the bottleneck, try engineering better features instead
- "stop" — accuracy is good enough (>75%) or no useful data exists

Reply in valid JSON only, no markdown:
{{"action": "<continue|focus_features|stop>", "reason": "<one sentence>"}}"""

    response = model.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        result = json.loads(text)
        action = result.get("action", "continue")
        print(f"[gemini] Next action: {action} — {result.get('reason', '')}")
        return action
    except json.JSONDecodeError:
        return "continue"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str, log_file):
    ts  = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    log_file.write(line + "\n")
    log_file.flush()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

TRIED_DATASETS_PATH = AGENT_DIR / "tried_datasets.json"


def _load_tried() -> set:
    if TRIED_DATASETS_PATH.exists():
        return set(json.load(open(TRIED_DATASETS_PATH)))
    return set()


def _save_tried(tried: set):
    with open(TRIED_DATASETS_PATH, "w") as f:
        json.dump(sorted(tried), f, indent=2)


def run_once(model, log_file) -> str:
    """Run one full improvement cycle. Returns next action."""
    _log("=== Starting improvement cycle ===", log_file)

    tried_refs = _load_tried()

    # Step 1 — Diagnose
    _log("Step 1: Diagnosing weak classes...", log_file)
    diagnosis = agent_diagnose.run(top_n=5, max_parts=300)
    _log(f"  Accuracy={diagnosis['overall_accuracy']*100:.1f}%  Weakest={diagnosis['weakest_classes'][0]['class']}", log_file)

    # Step 2 — Search
    _log("Step 2: Searching for datasets...", log_file)
    weak_class_names = [c["class"] for c in diagnosis["weakest_classes"]]
    search_results = agent_search.search_all(weak_class_names)

    # Filter out already-tried datasets
    search_results["kaggle"] = [d for d in search_results["kaggle"] if d["ref"] not in tried_refs]
    search_results["github"] = [d for d in search_results["github"] if d["ref"] not in tried_refs]
    search_results["total_found"] = len(search_results["kaggle"]) + len(search_results["github"])
    _log(f"  Found {search_results['total_found']} new candidates ({len(tried_refs)} already tried)", log_file)

    if search_results["total_found"] == 0:
        _log("  No new candidates found — skipping retrain this cycle", log_file)
        return "continue"

    # Step 3 — Gemini picks dataset (LLM call #1)
    _log("Step 3: Asking Gemini to pick best dataset...", log_file)
    chosen = _gemini_pick_dataset(diagnosis, search_results, model)

    retrain_result = {"accuracy": diagnosis["overall_accuracy"], "model_path": "", "n_faces": 0, "version_tag": "no_new_data"}
    promote_result = {"promoted": False, "reason": "No dataset chosen", "new_best": diagnosis["overall_accuracy"]}

    if chosen and chosen.get("source") == "kaggle" and chosen.get("ref"):
        chosen_ref = chosen["ref"]
        tried_refs.add(chosen_ref)
        _save_tried(tried_refs)

        # Step 4 — Download
        _log(f"Step 4: Downloading {chosen_ref}...", log_file)
        try:
            data_dir = agent_retrain.download_kaggle_dataset(chosen_ref)
            step_count = agent_retrain.count_step_files(data_dir)
            _log(f"  Downloaded — {step_count} STEP files found", log_file)

            if step_count == 0:
                _log("  No STEP files in dataset — skipping retrain", log_file)
            else:
                # Step 5 — Retrain
                _log("Step 5: Retraining...", log_file)
                ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
                retrain_result = agent_retrain.retrain(new_data_dir=data_dir, version_tag=f"agent_{ts_tag}")
                _log(f"  Candidate accuracy: {retrain_result['accuracy']*100:.2f}%", log_file)

                # Step 6 — Promote
                _log("Step 6: Evaluating promotion...", log_file)
                promote_result = agent_promote.promote(retrain_result)
                _log(f"  {promote_result['reason']}", log_file)

        except Exception as e:
            _log(f"  Error during download/retrain: {e}", log_file)
    else:
        if chosen:
            tried_refs.add(chosen.get("ref", ""))
            _save_tried(tried_refs)
        _log("  Gemini found no suitable Kaggle dataset this cycle", log_file)

    # Step 7 — Gemini evaluates outcome (LLM call #2)
    _log("Step 7: Asking Gemini to evaluate outcome...", log_file)
    action = _gemini_evaluate_result(diagnosis, retrain_result, promote_result, model)

    _log(f"=== Cycle complete. Next action: {action} ===\n", log_file)
    return action


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set.")
        print("Get a free key at https://aistudio.google.com/apikey")
        sys.exit(1)

    kaggle_dir = Path.home() / ".kaggle"
    has_kaggle = (kaggle_dir / "kaggle.json").exists() or (kaggle_dir / "access_token").exists() or os.environ.get("KAGGLE_API_TOKEN")
    if not has_kaggle:
        print("WARNING: No Kaggle credentials found — Kaggle search will be skipped.")
        print("  To enable: place access_token at", kaggle_dir / "access_token")

    model = genai.Client(api_key=api_key)

    log_path = LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    print(f"Logging to {log_path}")

    with open(log_path, "w") as log_file:
        if args.once:
            run_once(model, log_file)
        else:
            cycle = 0
            while True:
                cycle += 1
                print(f"\n{'='*60}\nCycle {cycle}  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'='*60}")
                try:
                    action = run_once(model, log_file)
                except Exception as e:
                    _log(f"Cycle failed with error: {e}", log_file)
                    action = "continue"

                if action == "stop":
                    _log("Agent decided to stop. Exiting.", log_file)
                    break

                if args.once:
                    break

                _log(f"Sleeping {LOOP_SLEEP_SEC//60} minutes until next cycle...", log_file)
                time.sleep(LOOP_SLEEP_SEC)


if __name__ == "__main__":
    main()
