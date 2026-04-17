"""
Classification accuracy test against labeled sample files.

Run: python -m tests.test_classification_accuracy
From: file-classifier/
"""

import os
import sys
import json
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.classifier.classifier import classify_file
from app.utils.file_utils import SUPPORTED_EXTENSIONS

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_files"

# Map folder names to expected classification
FOLDER_TO_EXPECTED = {
    "BER": "BER",
    "MPBC": "MPBC",
    "Quotation": "Quotation",
    "RFQ": "RFQ",
    "eauc": "E-Auction",
    # These categories are not one of the 5 named types → expect "Other"
    "20K": "Other",
    "Approval": "Other",
    "Project File": "Other",
    "Single Supplier Justification": "Other",
}


def run_test():
    results = []
    skipped = []
    errors = []

    folders = sorted([d for d in SAMPLE_DIR.iterdir() if d.is_dir()])

    for folder in folders:
        expected = FOLDER_TO_EXPECTED.get(folder.name)
        if expected is None:
            print(f"  [SKIP] Unknown folder: {folder.name}")
            continue

        files = sorted([
            f for f in folder.iterdir()
            if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ])

        unsupported = [
            f for f in folder.iterdir()
            if f.is_file() and not f.name.startswith(".") and f.suffix.lower() not in SUPPORTED_EXTENSIONS
        ]
        for f in unsupported:
            skipped.append({"file": f.name, "folder": folder.name, "reason": f"Unsupported: {f.suffix}"})

        for filepath in files:
            print(f"  Classifying: {folder.name}/{filepath.name} ... ", end="", flush=True)
            try:
                with open(filepath, "rb") as f:
                    file_bytes = f.read()

                result = classify_file(file_bytes, filepath.name)
                correct = result["classification"] == expected
                status = "PASS" if correct else "FAIL"
                print(f"{status} → {result['classification']} (conf: {result['confidence']}) [{result['processing_time_ms']}ms]")

                results.append({
                    "file": filepath.name,
                    "folder": folder.name,
                    "expected": expected,
                    "predicted": result["classification"],
                    "confidence": result["confidence"],
                    "reason": result["reason"],
                    "key_signals": result.get("key_signals", []),
                    "fields_matched": result.get("fields_matched", []),
                    "fields_missing": result.get("fields_missing", []),
                    "processing_time_ms": result["processing_time_ms"],
                    "correct": correct,
                })
            except Exception as e:
                print(f"ERROR → {e}")
                errors.append({"file": filepath.name, "folder": folder.name, "error": str(e)})

    return results, skipped, errors


def print_report(results, skipped, errors):
    print("\n" + "=" * 80)
    print("CLASSIFICATION ACCURACY REPORT")
    print("=" * 80)

    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = (correct / total * 100) if total > 0 else 0

    print(f"\nOverall: {correct}/{total} correct ({accuracy:.1f}%)")
    print(f"Errors: {len(errors)}")
    print(f"Skipped (unsupported format): {len(skipped)}")

    # Per-category breakdown
    categories = sorted(set(r["expected"] for r in results))
    print(f"\n{'Category':<15} {'Correct':<10} {'Total':<8} {'Accuracy':<10} {'Avg Conf':<10} {'Avg Time':<10}")
    print("-" * 63)
    for cat in categories:
        cat_results = [r for r in results if r["expected"] == cat]
        cat_correct = sum(1 for r in cat_results if r["correct"])
        cat_total = len(cat_results)
        cat_acc = (cat_correct / cat_total * 100) if cat_total > 0 else 0
        avg_conf = sum(r["confidence"] for r in cat_results) / cat_total if cat_total > 0 else 0
        avg_time = sum(r["processing_time_ms"] for r in cat_results) / cat_total if cat_total > 0 else 0
        print(f"{cat:<15} {cat_correct:<10} {cat_total:<8} {cat_acc:<10.1f} {avg_conf:<10.2f} {avg_time:<10.0f}ms")

    # Misclassifications
    misses = [r for r in results if not r["correct"]]
    if misses:
        print(f"\n{'=' * 80}")
        print("MISCLASSIFICATIONS")
        print("=" * 80)
        for r in misses:
            print(f"\n  File: {r['folder']}/{r['file']}")
            print(f"  Expected: {r['expected']} → Predicted: {r['predicted']} (conf: {r['confidence']})")
            print(f"  Reason: {r['reason']}")
            print(f"  Key signals: {r['key_signals']}")
    else:
        print("\n  No misclassifications!")

    # Skipped files
    if skipped:
        print(f"\n{'=' * 80}")
        print("SKIPPED FILES (unsupported format)")
        print("=" * 80)
        for s in skipped:
            print(f"  {s['folder']}/{s['file']} — {s['reason']}")

    # Errors
    if errors:
        print(f"\n{'=' * 80}")
        print("ERRORS")
        print("=" * 80)
        for e in errors:
            print(f"  {e['folder']}/{e['file']} — {e['error']}")

    # Save full results to JSON
    output_path = Path(__file__).resolve().parent / "test_results.json"
    with open(output_path, "w") as f:
        json.dump({"results": results, "skipped": skipped, "errors": errors}, f, indent=2)
    print(f"\nFull results saved to: {output_path}")


if __name__ == "__main__":
    print("=" * 80)
    print("FILE CLASSIFICATION ACCURACY TEST")
    print(f"Sample directory: {SAMPLE_DIR}")
    print("=" * 80)

    start = time.time()
    results, skipped, errors = run_test()
    elapsed = time.time() - start

    print_report(results, skipped, errors)
    print(f"\nTotal test time: {elapsed:.1f}s")
