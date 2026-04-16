"""
train.py
─────────
Training script for CampDetector (Phase 3).

Handles both synthetic and real satellite imagery.
Automatically uses best available data.

Run:
    python -m ml.download_real_data    ← Download real imagery
    python -m ml.train                 ← Train the model
"""

from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

TORCH_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, WeightedRandomSampler
    import torchvision.transforms as T
    import torchvision.datasets as datasets
    TORCH_AVAILABLE = True
except ImportError:
    pass

if TYPE_CHECKING:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, WeightedRandomSampler
    import torchvision.transforms as T
    import torchvision.datasets as datasets

DATA_DIR = Path(__file__).parent / "data"
WEIGHTS_DIR = Path(__file__).parent / "weights"
LOGS_DIR = Path(__file__).parent / "logs"

EPOCHS = 30
BATCH_SIZE = 16
LR = 3e-4
LR_MIN = 1e-6
NUM_CLASSES = 2
PATIENCE = 8  # Early stopping patience


def get_transforms(
    is_real: bool = False,
) -> tuple[T.Compose, T.Compose]:
    """
    Get transforms. Use stronger augmentation for real data.
    """
    if is_real:
        train_tf = T.Compose([
            T.Resize((224, 224)),
            T.RandomHorizontalFlip(),
            T.RandomVerticalFlip(),
            T.RandomRotation(20),
            T.RandomAffine(
                degrees=0, translate=(0.1, 0.1), scale=(0.9, 1.1)
            ),
            T.ColorJitter(
                brightness=0.3, contrast=0.3, saturation=0.2, hue=0.05
            ),
            T.RandomGrayscale(p=0.05),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            T.RandomErasing(p=0.1),
        ])
    else:
        train_tf = T.Compose([
            T.Resize((224, 224)),
            T.RandomHorizontalFlip(),
            T.RandomVerticalFlip(),
            T.RandomRotation(15),
            T.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    val_tf = T.Compose([
        T.Resize((224, 224)),
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    return train_tf, val_tf


def _count_real_images(directory: Path) -> int:
    """Count images with 'real_' prefix."""
    count = 0
    for cls_dir in directory.iterdir():
        if cls_dir.is_dir():
            count += len(list(cls_dir.glob("real_*")))
    return count


def _get_class_weights(dataset: datasets.ImageFolder) -> torch.Tensor:
    """Calculate class weights for imbalanced datasets."""
    class_counts = [0] * NUM_CLASSES
    for _, label in dataset:
        class_counts[label] += 1

    total = sum(class_counts)
    weights = [
        total / (NUM_CLASSES * c) if c > 0 else 0.0
        for c in class_counts
    ]
    return torch.FloatTensor(weights)


def train() -> None:
    """Run the full training pipeline."""
    if not TORCH_AVAILABLE:
        print("❌ PyTorch is required. Install: pip install torch torchvision")
        return

    print("=" * 60)
    print("  EagleEye-Nigeria — CampDetector Training")
    print("=" * 60)

    train_dir = DATA_DIR / "train"
    val_dir = DATA_DIR / "val"

    if not train_dir.exists() or not any(train_dir.iterdir()):
        print(f"\n  ❌ Training data not found at {train_dir}")
        print("  Options:")
        print("    python -m ml.setup_training_data    ← Synthetic data")
        print("    python -m ml.download_real_data     ← Real satellite imagery")
        return

    # Detect data type
    real_count = _count_real_images(train_dir)
    total_files = sum(
        len(list(d.glob("*.*")))
        for d in train_dir.iterdir()
        if d.is_dir()
    )
    is_real = real_count > total_files * 0.3  # >30% real = use real augmentation

    data_type = "REAL satellite" if is_real else "SYNTHETIC"
    print(f"\n  📊 Data type: {data_type}")
    print(f"     Real images: {real_count}, Total: {total_files}")

    train_tf, val_tf = get_transforms(is_real=is_real)

    train_ds = datasets.ImageFolder(train_dir, transform=train_tf)
    val_ds = datasets.ImageFolder(val_dir, transform=val_tf)

    if len(train_ds) == 0:
        print("  ❌ No training images found.")
        return

    # Adjust for Windows
    num_workers = 0 if os.name == "nt" else 2

    # Use weighted sampling if classes are imbalanced
    class_weights = _get_class_weights(train_ds)
    sample_weights = [
        float(class_weights[label]) for _, label in train_ds
    ]
    sampler = WeightedRandomSampler(sample_weights, len(train_ds))

    train_loader = DataLoader(
        train_ds,
        batch_size=BATCH_SIZE,
        sampler=sampler,
        num_workers=num_workers,
        pin_memory=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
    )

    print(f"  Training samples: {len(train_ds)}")
    print(f"  Validation samples: {len(val_ds)}")
    print(f"  Classes: {train_ds.classes}")
    print(f"  Class mapping: {train_ds.class_to_idx}")
    print(
        f"  Class balance: "
        f"{[sum(1 for _, l in train_ds if l == i) for i in range(NUM_CLASSES)]}"
    )

    # Build model
    from ml.detector import CampDetector
    detector = CampDetector()

    if detector.model is None:
        print("  ❌ Failed to build model.")
        return

    model = detector.model
    device = detector.device

    # Use weighted loss for class imbalance
    criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
    optimizer = optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=EPOCHS, eta_min=LR_MIN
    )

    print(f"  Device: {device}")
    print(f"  Epochs: {EPOCHS}, Batch: {BATCH_SIZE}, LR: {LR}")
    print("  Optimizer: AdamW + CosineAnnealing")
    print(f"  Early stopping patience: {PATIENCE}")
    print(
        f"\n  {'Epoch':>5} | {'Loss':>8} | {'Train':>7} | "
        f"{'Val':>7} | {'LR':>10} | {'Time':>5}"
    )
    print(f"  {'─' * 58}")

    best_val_acc = 0.0
    patience_counter = 0
    history: list[dict[str, Any]] = []
    final_epoch = 0

    for epoch in range(1, EPOCHS + 1):
        final_epoch = epoch
        epoch_start = time.time()

        # ── Training ──
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for images, labels in train_loader:
            images = images.to(device)
            labels = labels.to(device)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()

            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

            optimizer.step()
            train_loss += loss.item() * images.size(0)
            train_correct += int((outputs.argmax(1) == labels).sum().item())
            train_total += images.size(0)

        scheduler.step()

        # ── Validation ──
        model.eval()
        val_correct = 0
        val_total = 0
        val_loss = 0.0

        with torch.no_grad():
            for val_images, val_labels in val_loader:
                val_images = val_images.to(device)
                val_labels = val_labels.to(device)

                val_outputs = model(val_images)
                v_loss = criterion(val_outputs, val_labels)
                val_loss += v_loss.item() * val_images.size(0)
                val_correct += int(
                    (val_outputs.argmax(1) == val_labels).sum().item()
                )
                val_total += val_images.size(0)

        train_acc = train_correct / train_total if train_total > 0 else 0.0
        val_acc = val_correct / val_total if val_total > 0 else 0.0
        avg_loss = train_loss / train_total if train_total > 0 else 0.0
        current_lr = float(optimizer.param_groups[0]["lr"])
        elapsed = time.time() - epoch_start

        history.append({
            "epoch": epoch,
            "loss": round(avg_loss, 4),
            "train_acc": round(train_acc, 4),
            "val_acc": round(val_acc, 4),
            "lr": round(current_lr, 8),
        })

        marker = ""
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience_counter = 0
            detector.save_weights()
            marker = " ✓ saved"
        else:
            patience_counter += 1

        print(
            f"  {epoch:5d} | {avg_loss:8.4f} | {train_acc:6.1%} | "
            f"{val_acc:6.1%} | {current_lr:10.2e} | "
            f"{elapsed:4.1f}s{marker}"
        )

        # Early stopping
        if patience_counter >= PATIENCE:
            print(
                f"\n  ⚠️  Early stopping at epoch {epoch} "
                f"(no improvement for {PATIENCE} epochs)"
            )
            break

    # ── Save training log ──
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "training_log.json"

    log_data: dict[str, Any] = {
        "epochs_run": final_epoch,
        "epochs_max": EPOCHS,
        "batch_size": BATCH_SIZE,
        "learning_rate": LR,
        "best_val_acc": round(best_val_acc, 4),
        "data_type": data_type,
        "real_images": real_count,
        "total_images": total_files,
        "history": history,
        "classes": train_ds.classes,
        "train_samples": len(train_ds),
        "val_samples": len(val_ds),
    }

    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2)

    print(f"\n  {'=' * 58}")
    print("  ✅ Training complete!")
    print(f"  ✅ Best validation accuracy: {best_val_acc:.1%}")
    print(f"  ✅ Data type: {data_type}")
    print(f"  ✅ Weights: {WEIGHTS_DIR / 'camp_detector_v1.pt'}")
    print(f"  ✅ Log: {log_path}")
    print(f"  {'=' * 58}")


if __name__ == "__main__":
    train()