"""
evaluate.py
────────────
Evaluate trained CampDetector model with detailed metrics.

Run: python -m ml.evaluate
"""

import os
import sys
import json
from pathlib import Path
from collections import defaultdict

try:
    import torch
    import torchvision.transforms as T
    import torchvision.datasets as datasets
    from torch.utils.data import DataLoader
    import numpy as np
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

DATA_DIR = Path(__file__).parent / "data"
LOGS_DIR = Path(__file__).parent / "logs"


def evaluate():
    if not TORCH_AVAILABLE:
        print("❌ PyTorch required.")
        return

    print("=" * 60)
    print("  EagleEye-Nigeria — Model Evaluation")
    print("=" * 60)

    val_dir = DATA_DIR / "val"
    if not val_dir.exists():
        print("  ❌ Validation data not found.")
        return

    val_tf = T.Compose([
        T.Resize((224, 224)),
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    val_ds = datasets.ImageFolder(val_dir, transform=val_tf)
    num_workers = 0 if os.name == "nt" else 2
    val_loader = DataLoader(val_ds, batch_size=1, shuffle=False, num_workers=num_workers)

    print(f"\n  Validation samples: {len(val_ds)}")
    print(f"  Classes: {val_ds.classes}")

    from ml.detector import CampDetector
    detector = CampDetector()

    if detector.model is None:
        print("  ❌ Model not available.")
        return

    model = detector.model
    device = detector.device
    model.eval()

    # Per-class tracking
    class_names = val_ds.classes
    confusion = defaultdict(lambda: defaultdict(int))  # confusion[true][pred]
    all_scores = []

    with torch.no_grad():
        for images, labels in val_loader:
            images = images.to(device)
            outputs = model(images)
            probs = torch.softmax(outputs, dim=1)
            pred = outputs.argmax(1).item()
            true = labels.item()
            conf = probs[0][pred].item()

            confusion[true][pred] += 1
            all_scores.append({
                "true": true,
                "pred": pred,
                "confidence": round(conf, 4),
                "correct": pred == true,
            })

    # Calculate metrics
    total = len(all_scores)
    correct = sum(1 for s in all_scores if s["correct"])
    accuracy = correct / total if total > 0 else 0

    print(f"\n  ── Results ──")
    print(f"  Overall Accuracy: {accuracy:.1%} ({correct}/{total})")

    # Per-class metrics
    print(f"\n  ── Per-Class Metrics ──")
    print(f"  {'Class':<30} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
    print(f"  {'─' * 72}")

    for cls_idx, cls_name in enumerate(class_names):
        tp = confusion[cls_idx][cls_idx]
        fp = sum(confusion[other][cls_idx] for other in range(len(class_names)) if other != cls_idx)
        fn = sum(confusion[cls_idx][other] for other in range(len(class_names)) if other != cls_idx)
        support = tp + fn

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        print(f"  {cls_name:<30} {precision:>10.3f} {recall:>10.3f} {f1:>10.3f} {support:>10d}")

    # Confusion matrix
    print(f"\n  ── Confusion Matrix ──")
    print(f"  {'':>25} Predicted:")
    print(f"  {'':>25} {'Legal':>12} {'Suspicious':>12}")
    for true_idx, true_name in enumerate(class_names):
        row = f"  True {true_name:>18}:"
        for pred_idx in range(len(class_names)):
            count = confusion[true_idx][pred_idx]
            row += f" {count:>12d}"
        print(row)

    # Confidence analysis
    correct_confs = [s["confidence"] for s in all_scores if s["correct"]]
    wrong_confs = [s["confidence"] for s in all_scores if not s["correct"]]

    print(f"\n  ── Confidence Analysis ──")
    if correct_confs:
        print(f"  Correct predictions:  avg={np.mean(correct_confs):.3f}, min={np.min(correct_confs):.3f}, max={np.max(correct_confs):.3f}")
    if wrong_confs:
        print(f"  Wrong predictions:    avg={np.mean(wrong_confs):.3f}, min={np.min(wrong_confs):.3f}, max={np.max(wrong_confs):.3f}")

    # Save evaluation report
    report = {
        "accuracy": round(accuracy, 4),
        "total_samples": total,
        "correct": correct,
        "confusion_matrix": {
            class_names[i]: {class_names[j]: confusion[i][j] for j in range(len(class_names))}
            for i in range(len(class_names))
        },
        "per_sample": all_scores,
    }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = LOGS_DIR / "evaluation_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n  ✅ Report saved to: {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    evaluate()