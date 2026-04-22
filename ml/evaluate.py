"""
evaluate.py
────────────
Evaluate trained CampDetector model with detailed metrics.
Includes test-time augmentation (TTA) and threshold analysis.

Run: python -m ml.evaluate
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from collections import defaultdict
from typing import TYPE_CHECKING, Any

TORCH_AVAILABLE = False

try:
    import torch
    import torchvision.transforms as T
    import torchvision.datasets as datasets
    from torch.utils.data import DataLoader
    import numpy as np
    TORCH_AVAILABLE = True
except ImportError:
    pass

if TYPE_CHECKING:
    import torch
    import torchvision.transforms as T
    import torchvision.datasets as datasets
    from torch.utils.data import DataLoader
    import numpy as np

DATA_DIR = Path(__file__).parent / "data"
LOGS_DIR = Path(__file__).parent / "logs"


def evaluate() -> None:
    """Run full evaluation with TTA and threshold analysis."""
    if not TORCH_AVAILABLE:
        print("❌ PyTorch required: pip install torch torchvision numpy")
        return

    print("=" * 60)
    print("  EagleEye-Nigeria — Model Evaluation v2")
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
    val_loader = DataLoader(
        val_ds, batch_size=1, shuffle=False, num_workers=num_workers
    )

    print(f"\n  Validation samples: {len(val_ds)}")
    print(f"  Classes: {val_ds.classes}")

    from ml.detector import CampDetector
    detector = CampDetector()

    if detector.model is None:
        print("  ❌ Model not available.")
        return

    model = detector.model
    device = detector.device
    assert device is not None
    model.eval()

    class_names: list[str] = val_ds.classes
    num_classes = len(class_names)

    # ── Standard evaluation ──
    print("\n  ── Standard Evaluation (no TTA) ──")
    confusion_std: dict[int, dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    all_scores: list[dict[str, Any]] = []

    with torch.no_grad():
        for images, labels in val_loader:
            images = images.to(device)
            outputs = model(images)
            probs = torch.softmax(outputs, dim=1)
            pred = int(outputs.argmax(1).item())
            true = int(labels.item())
            conf = float(probs[0][pred].item())
            conf_class1 = float(probs[0][1].item())

            confusion_std[true][pred] += 1
            all_scores.append({
                "true": true,
                "pred": pred,
                "confidence": round(conf, 4),
                "confidence_suspicious": round(conf_class1, 4),
                "correct": pred == true,
            })

    total = len(all_scores)
    correct = sum(1 for s in all_scores if s["correct"])
    accuracy = correct / total if total > 0 else 0.0

    print(f"  Overall Accuracy: {accuracy:.1%} ({correct}/{total})")
    _print_metrics(confusion_std, class_names, num_classes)

    # ── TTA Evaluation ──
    print("\n  ── TTA Evaluation (4x augmented) ──")
    confusion_tta: dict[int, dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    tta_scores: list[dict[str, Any]] = []

    with torch.no_grad():
        for images, labels in val_loader:
            images = images.to(device)

            # Collect augmented predictions
            all_probs: list[torch.Tensor] = []

            # Original
            probs = torch.softmax(model(images), dim=1)
            all_probs.append(probs)

            # Horizontal flip
            probs = torch.softmax(
                model(torch.flip(images, [3])), dim=1
            )
            all_probs.append(probs)

            # Vertical flip
            probs = torch.softmax(
                model(torch.flip(images, [2])), dim=1
            )
            all_probs.append(probs)

            # Both flips
            probs = torch.softmax(
                model(torch.flip(images, [2, 3])), dim=1
            )
            all_probs.append(probs)

            avg_probs = torch.stack(all_probs).mean(dim=0)
            pred = int(avg_probs.argmax(1).item())
            true = int(labels.item())
            conf = float(avg_probs[0][pred].item())

            confusion_tta[true][pred] += 1
            tta_scores.append({
                "true": true,
                "pred": pred,
                "confidence": round(conf, 4),
                "correct": pred == true,
            })

    tta_correct = sum(1 for s in tta_scores if s["correct"])
    tta_accuracy = tta_correct / total if total > 0 else 0.0

    print(f"  TTA Accuracy: {tta_accuracy:.1%} ({tta_correct}/{total})")
    _print_metrics(confusion_tta, class_names, num_classes)

    # ── Threshold Analysis ──
    print("\n  ── Optimal Threshold Analysis ──")
    print(
        f"  {'Threshold':>10} {'Accuracy':>10} {'Flagged':>10} "
        f"{'Missed':>10}"
    )
    print(f"  {'─' * 42}")

    for threshold in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
        thresh_correct = 0
        flagged = 0
        missed = 0
        for s in all_scores:
            suspicious_conf = s["confidence_suspicious"]
            thresh_pred = 1 if suspicious_conf >= threshold else 0
            if thresh_pred == s["true"]:
                thresh_correct += 1
            if thresh_pred == 1:
                flagged += 1
            if s["true"] == 1 and thresh_pred == 0:
                missed += 1

        thresh_acc = thresh_correct / total if total > 0 else 0.0
        print(
            f"  {threshold:10.2f} {thresh_acc:10.1%} "
            f"{flagged:10d} {missed:10d}"
        )

    # ── Confidence Analysis ──
    correct_confs = [s["confidence"] for s in all_scores if s["correct"]]
    wrong_confs = [s["confidence"] for s in all_scores if not s["correct"]]

    print("\n  ── Confidence Analysis ──")
    if correct_confs:
        arr = np.array(correct_confs)
        print(
            f"  Correct predictions:  "
            f"avg={float(np.mean(arr)):.3f}, "
            f"min={float(np.min(arr)):.3f}, "
            f"max={float(np.max(arr)):.3f}, "
            f"std={float(np.std(arr)):.3f}"
        )
    if wrong_confs:
        arr = np.array(wrong_confs)
        print(
            f"  Wrong predictions:    "
            f"avg={float(np.mean(arr)):.3f}, "
            f"min={float(np.min(arr)):.3f}, "
            f"max={float(np.max(arr)):.3f}, "
            f"std={float(np.std(arr)):.3f}"
        )

    # ── Save report ──
    report: dict[str, Any] = {
        "standard_accuracy": round(accuracy, 4),
        "tta_accuracy": round(tta_accuracy, 4),
        "total_samples": total,
        "standard_correct": correct,
        "tta_correct": tta_correct,
        "confusion_matrix_standard": {
            class_names[i]: {
                class_names[j]: confusion_std[i][j]
                for j in range(num_classes)
            }
            for i in range(num_classes)
        },
        "confusion_matrix_tta": {
            class_names[i]: {
                class_names[j]: confusion_tta[i][j]
                for j in range(num_classes)
            }
            for i in range(num_classes)
        },
        "per_sample_standard": all_scores,
        "per_sample_tta": tta_scores,
    }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = LOGS_DIR / "evaluation_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n  ✅ Report saved to: {report_path}")
    print("=" * 60)


def _print_metrics(
    confusion: dict[int, dict[int, int]],
    class_names: list[str],
    num_classes: int,
) -> None:
    """Print per-class precision, recall, F1 and confusion matrix."""
    print(
        f"\n  {'Class':<30} {'Precision':>10} {'Recall':>10} "
        f"{'F1':>10} {'Support':>10}"
    )
    print(f"  {'─' * 72}")

    macro_p = 0.0
    macro_r = 0.0
    macro_f1 = 0.0

    for cls_idx, cls_name in enumerate(class_names):
        tp = confusion[cls_idx][cls_idx]
        fp = sum(
            confusion[other][cls_idx]
            for other in range(num_classes)
            if other != cls_idx
        )
        fn = sum(
            confusion[cls_idx][other]
            for other in range(num_classes)
            if other != cls_idx
        )
        support = tp + fn

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        macro_p += precision
        macro_r += recall
        macro_f1 += f1

        print(
            f"  {cls_name:<30} {precision:>10.3f} {recall:>10.3f} "
            f"{f1:>10.3f} {support:>10d}"
        )

    macro_p /= num_classes
    macro_r /= num_classes
    macro_f1 /= num_classes
    print(f"  {'─' * 72}")
    print(
        f"  {'Macro Average':<30} {macro_p:>10.3f} {macro_r:>10.3f} "
        f"{macro_f1:>10.3f}"
    )

    # Confusion matrix
    print(f"\n  {'':>25} Predicted:")
    header = f"  {'':>25}"
    for name in class_names:
        header += f" {name[:12]:>12}"
    print(header)

    for true_idx, true_name in enumerate(class_names):
        row = f"  True {true_name:>18}:"
        for pred_idx in range(num_classes):
            count = confusion[true_idx][pred_idx]
            row += f" {count:>12d}"
        print(row)


if __name__ == "__main__":
    evaluate()