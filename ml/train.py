"""
train.py
─────────
Training script for CampDetector (Phase 3).

v2.1 — Fixed overfitting issues from v2.0:
  - Reduced backbone LR (was too aggressive, destabilizing Stage 2)
  - Replaced CosineAnnealingWarmRestarts with CosineAnnealingLR
    (warm restarts caused LR spikes that undid progress)
  - Increased weight decay (more regularization)
  - Reduced mixup/cutmix aggressiveness
  - Explicit backbone_lr / head_lr (no more confusing multipliers)
  - Simplified augmentation pipeline (removed slow ops)
  - Dev/Prod mode via EAGLEEYE_MODE environment variable

Modes:
  EAGLEEYE_MODE=dev   → Fast iteration (~10-15 min CPU, ~2-3 min GPU)
  EAGLEEYE_MODE=prod  → Full training (~2-3 hours CPU, ~15-20 min GPU)

Run:
    python -m ml.train                             ← Dev mode (default)
    set EAGLEEYE_MODE=prod && python -m ml.train   ← Prod mode (Windows)
    EAGLEEYE_MODE=prod python -m ml.train          ← Prod mode (Linux/Mac)
"""

from __future__ import annotations

import copy
import math
import os
import sys
import json
import time
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

TORCH_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torch.optim as optim
    from torch.utils.data import DataLoader, WeightedRandomSampler
    import torchvision.transforms as T
    import torchvision.datasets as datasets
    import numpy as np
    TORCH_AVAILABLE = True
except ImportError:
    pass

if TYPE_CHECKING:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torch.optim as optim
    from torch.utils.data import DataLoader, WeightedRandomSampler
    import torchvision.transforms as T
    import torchvision.datasets as datasets
    import numpy as np

DATA_DIR = Path(__file__).parent / "data"
WEIGHTS_DIR = Path(__file__).parent / "weights"
LOGS_DIR = Path(__file__).parent / "logs"

# ═══════════════════════════════════════════════════════
# MODE DETECTION
# Set environment variable: EAGLEEYE_MODE=dev or EAGLEEYE_MODE=prod
# Default: dev (fast local training)
#
# Windows:    set EAGLEEYE_MODE=prod
# Linux/Mac:  export EAGLEEYE_MODE=prod
# Railway:    Add EAGLEEYE_MODE=prod in dashboard env vars
# ═══════════════════════════════════════════════════════
TRAIN_MODE = os.getenv("EAGLEEYE_MODE", "dev").lower().strip()
IS_DEV = TRAIN_MODE != "prod"

# ═══════════════════════════════════════════════════════
# HYPERPARAMETERS
# Dev mode:  Fast iteration, ~10-15 min on CPU
# Prod mode: Full training, ~2-3 hours CPU, best accuracy
# ═══════════════════════════════════════════════════════
NUM_CLASSES = 2

if IS_DEV:
    # ── DEV: Speed-optimized for quick local iteration ──
    EPOCHS_STAGE1 = 3
    EPOCHS_STAGE2 = 7
    BATCH_SIZE = 32
    GRAD_ACCUMULATION = 1       # No accumulation (fewer steps)
    LR_HEAD = 3e-3              # Higher LR (converge faster)
    LR_BACKBONE_S2 = 1e-4      # Higher backbone LR (faster tuning)
    LR_HEAD_S2 = 1e-3           # Higher head LR
    LR_MIN = 1e-6
    WEIGHT_DECAY = 5e-4
    PATIENCE = 4                # Stop early if no improvement
    LABEL_SMOOTHING = 0.1
    MIXUP_ALPHA = 0.2
    CUTMIX_ALPHA = 0.5
    MIXUP_PROB = 0.5
    EMA_DECAY = 0.998           # Faster EMA adaptation
    MIX_PROBABILITY_S1 = 0.2   # Less mixing in dev (faster)
    MIX_PROBABILITY_S2 = 0.2
else:
    # ── PROD: Accuracy-optimized for deployment ──
    EPOCHS_STAGE1 = 10
    EPOCHS_STAGE2 = 30
    BATCH_SIZE = 16
    GRAD_ACCUMULATION = 2       # Effective batch = 32
    LR_HEAD = 1e-3
    LR_BACKBONE_S2 = 3e-5      # Conservative backbone LR
    LR_HEAD_S2 = 3e-4
    LR_MIN = 1e-7
    WEIGHT_DECAY = 5e-4
    PATIENCE = 10
    LABEL_SMOOTHING = 0.1
    MIXUP_ALPHA = 0.2
    CUTMIX_ALPHA = 0.5
    MIXUP_PROB = 0.5
    EMA_DECAY = 0.999
    MIX_PROBABILITY_S1 = 0.3
    MIX_PROBABILITY_S2 = 0.3


# ═══════════════════════════════════════════════════════
# MIXUP / CUTMIX AUGMENTATION
# ═══════════════════════════════════════════════════════

def mixup_data(
    x: torch.Tensor,
    y: torch.Tensor,
    alpha: float = 0.2,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, float]:
    """Apply mixup augmentation."""
    if alpha > 0:
        lam = np.random.beta(alpha, alpha)
        lam = max(lam, 1 - lam)  # Ensure dominant image is at least 50%
    else:
        lam = 1.0

    batch_size = x.size(0)
    index = torch.randperm(batch_size, device=x.device)

    mixed_x = lam * x + (1 - lam) * x[index]
    y_a, y_b = y, y[index]
    return mixed_x, y_a, y_b, lam


def cutmix_data(
    x: torch.Tensor,
    y: torch.Tensor,
    alpha: float = 0.5,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, float]:
    """Apply CutMix augmentation."""
    if alpha > 0:
        lam = np.random.beta(alpha, alpha)
    else:
        lam = 1.0

    batch_size = x.size(0)
    index = torch.randperm(batch_size, device=x.device)

    _, _, h, w = x.shape

    cut_rat = math.sqrt(1.0 - lam)
    cut_w = int(w * cut_rat)
    cut_h = int(h * cut_rat)

    cx = random.randint(0, w)
    cy = random.randint(0, h)

    x1 = max(0, cx - cut_w // 2)
    y1 = max(0, cy - cut_h // 2)
    x2 = min(w, cx + cut_w // 2)
    y2 = min(h, cy + cut_h // 2)

    mixed_x = x.clone()
    mixed_x[:, :, y1:y2, x1:x2] = x[index, :, y1:y2, x1:x2]

    # Adjust lambda to actual cut area
    lam = 1 - ((x2 - x1) * (y2 - y1)) / (w * h)

    y_a, y_b = y, y[index]
    return mixed_x, y_a, y_b, lam


def mixup_criterion(
    criterion: nn.Module,
    pred: torch.Tensor,
    y_a: torch.Tensor,
    y_b: torch.Tensor,
    lam: float,
) -> torch.Tensor:
    """Compute mixed loss for mixup/cutmix."""
    return lam * criterion(pred, y_a) + (1 - lam) * criterion(pred, y_b)


# ═══════════════════════════════════════════════════════
# EXPONENTIAL MOVING AVERAGE (EMA)
# ═══════════════════════════════════════════════════════

class ModelEMA:
    """
    Maintains an exponential moving average of model parameters.
    EMA models often generalize better than the final model.
    """

    def __init__(self, model: nn.Module, decay: float = 0.999):
        self.ema_model = copy.deepcopy(model)
        self.ema_model.eval()
        self.decay = decay
        for p in self.ema_model.parameters():
            p.requires_grad_(False)

    def update(self, model: nn.Module) -> None:
        with torch.no_grad():
            for ema_p, model_p in zip(
                self.ema_model.parameters(), model.parameters()
            ):
                ema_p.data.mul_(self.decay).add_(
                    model_p.data, alpha=1 - self.decay
                )

    def state_dict(self) -> dict[str, Any]:
        return self.ema_model.state_dict()


# ═══════════════════════════════════════════════════════
# TRANSFORMS
# v2.1: Simplified — removed expensive ops that added
# compute cost without helping generalization.
# Dev mode uses lighter augmentation for speed.
# ═══════════════════════════════════════════════════════

def get_transforms(
    is_real: bool = False,
) -> tuple[T.Compose, T.Compose]:
    """
    Get data transforms.
    Training: moderate augmentation (strong enough for generalization,
              not so heavy it confuses the model).
    Validation: resize + normalize only.

    Dev mode uses slightly lighter augmentation for speed.
    """
    if IS_DEV:
        # ── DEV: Minimal augmentation for speed ──
        train_tf = T.Compose([
            T.Resize((224, 224)),
            T.RandomHorizontalFlip(),
            T.RandomVerticalFlip(),
            T.ColorJitter(
                brightness=0.2, contrast=0.2, saturation=0.1
            ),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
    elif is_real:
        # ── PROD + REAL: Full augmentation pipeline ──
        train_tf = T.Compose([
            T.Resize((240, 240)),
            T.RandomCrop(224),
            T.RandomHorizontalFlip(),
            T.RandomVerticalFlip(),
            T.RandomRotation(20),
            T.ColorJitter(
                brightness=0.3, contrast=0.3, saturation=0.2, hue=0.05
            ),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            T.RandomErasing(p=0.1, scale=(0.02, 0.1)),
        ])
    else:
        # ── PROD + SYNTHETIC: Moderate augmentation ──
        train_tf = T.Compose([
            T.Resize((240, 240)),
            T.RandomCrop(224),
            T.RandomHorizontalFlip(),
            T.RandomVerticalFlip(),
            T.RandomRotation(15),
            T.ColorJitter(
                brightness=0.2, contrast=0.2, saturation=0.1
            ),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    val_tf = T.Compose([
        T.Resize((224, 224)),
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    return train_tf, val_tf


# ═══════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════

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


def _validate(
    model: nn.Module,
    val_loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> tuple[float, float]:
    """Run validation and return (val_loss, val_accuracy)."""
    model.eval()
    val_correct = 0
    val_total = 0
    val_loss = 0.0

    with torch.no_grad():
        for images, labels in val_loader:
            images = images.to(device)
            labels = labels.to(device)
            outputs = model(images)
            loss = criterion(outputs, labels)
            val_loss += loss.item() * images.size(0)
            val_correct += int(
                (outputs.argmax(1) == labels).sum().item()
            )
            val_total += images.size(0)

    accuracy = val_correct / val_total if val_total > 0 else 0.0
    avg_loss = val_loss / val_total if val_total > 0 else 0.0
    return avg_loss, accuracy


def _validate_with_tta(
    model: nn.Module,
    val_loader: DataLoader,
    device: torch.device,
) -> float:
    """
    Validate with test-time augmentation (TTA) for final accuracy.
    Skipped in dev mode (just returns standard accuracy).
    """
    if IS_DEV:
        # Skip TTA in dev mode — too slow on CPU
        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for images, labels in val_loader:
                images = images.to(device)
                labels = labels.to(device)
                outputs = model(images)
                preds = outputs.argmax(dim=1)
                correct += int((preds == labels).sum().item())
                total += labels.size(0)
        return correct / total if total > 0 else 0.0

    # Full TTA for production
    model.eval()
    correct = 0
    total = 0

    with torch.no_grad():
        for images, labels in val_loader:
            images = images.to(device)
            labels = labels.to(device)

            all_probs: list[torch.Tensor] = []

            # Original
            probs = torch.softmax(model(images), dim=1)
            all_probs.append(probs)

            # Horizontal flip
            probs = torch.softmax(model(torch.flip(images, [3])), dim=1)
            all_probs.append(probs)

            # Vertical flip
            probs = torch.softmax(model(torch.flip(images, [2])), dim=1)
            all_probs.append(probs)

            # Both flips
            probs = torch.softmax(
                model(torch.flip(images, [2, 3])), dim=1
            )
            all_probs.append(probs)

            # Average predictions
            avg_probs = torch.stack(all_probs).mean(dim=0)
            preds = avg_probs.argmax(dim=1)

            correct += int((preds == labels).sum().item())
            total += labels.size(0)

    return correct / total if total > 0 else 0.0


# ═══════════════════════════════════════════════════════
# TRAINING STEP HELPER
# ═══════════════════════════════════════════════════════

def _train_one_epoch(
    model: nn.Module,
    train_loader: DataLoader,
    criterion: nn.Module,
    optimizer: optim.Optimizer,
    ema: ModelEMA,
    device: torch.device,
    mix_probability: float,
) -> tuple[float, float, int]:
    """
    Train for one epoch with optional mixup/cutmix.

    Returns:
        (average_loss, train_accuracy, global_steps_taken)
    """
    model.train()
    train_loss = 0.0
    train_correct = 0
    train_total = 0
    steps = 0
    batch_idx = 0  # Initialize before loop for Pylance

    optimizer.zero_grad()

    for batch_idx, (images, labels) in enumerate(train_loader):
        images = images.to(device)
        labels = labels.to(device)

        # ── Decide whether to apply mix augmentation ──
        use_mix = random.random() < mix_probability

        # Initialize unconditionally for Pylance
        targets_a: torch.Tensor = labels
        targets_b: torch.Tensor = labels
        lam: float = 1.0

        if use_mix:
            if random.random() < MIXUP_PROB:
                images, targets_a, targets_b, lam = mixup_data(
                    images, labels, MIXUP_ALPHA
                )
            else:
                images, targets_a, targets_b, lam = cutmix_data(
                    images, labels, CUTMIX_ALPHA
                )

        # ── Forward pass ──
        outputs = model(images)

        if use_mix:
            loss = mixup_criterion(
                criterion, outputs, targets_a, targets_b, lam
            )
        else:
            loss = criterion(outputs, labels)

        # ── Gradient accumulation ──
        scaled_loss = loss / GRAD_ACCUMULATION
        scaled_loss.backward()

        if (batch_idx + 1) % GRAD_ACCUMULATION == 0:
            torch.nn.utils.clip_grad_norm_(
                model.parameters(), max_norm=1.0
            )
            optimizer.step()
            optimizer.zero_grad()
            ema.update(model)
            steps += 1

        train_loss += loss.item() * images.size(0)

        if not use_mix:
            train_correct += int(
                (outputs.argmax(1) == labels).sum().item()
            )
            train_total += images.size(0)

    # Flush remaining accumulated gradients
    if (batch_idx + 1) % GRAD_ACCUMULATION != 0:
        torch.nn.utils.clip_grad_norm_(
            model.parameters(), max_norm=1.0
        )
        optimizer.step()
        optimizer.zero_grad()
        ema.update(model)
        steps += 1

    avg_loss = train_loss / max(train_total, 1)
    accuracy = train_correct / train_total if train_total > 0 else 0.0

    return avg_loss, accuracy, steps


# ═══════════════════════════════════════════════════════
# MAIN TRAINING PIPELINE
# ═══════════════════════════════════════════════════════

def train() -> None:
    """
    Two-stage training pipeline:
      Stage 1: Freeze backbone, train classifier head (fast convergence)
      Stage 2: Unfreeze backbone, fine-tune everything (discriminative LR)

    v2.1 changes:
      - CosineAnnealingLR replaces WarmRestarts (no more LR spikes)
      - Explicit backbone/head LRs (no confusing multiplier chains)
      - Lower mix probability
      - Higher weight decay (5e-4 not 1e-4)
      - Dev/Prod mode via EAGLEEYE_MODE env var
    """
    if not TORCH_AVAILABLE:
        print(
            "❌ PyTorch is required. "
            "Install: pip install torch torchvision numpy"
        )
        return

    mode_emoji = "🔧 DEV (fast)" if IS_DEV else "🚀 PRODUCTION (full)"
    target_msg = "quick baseline" if IS_DEV else "95%+ accuracy"

    print("=" * 60)
    print("  EagleEye-Nigeria — CampDetector Training v2.1")
    print(f"  Mode: {mode_emoji}")
    print(f"  Target: {target_msg}")
    print("=" * 60)

    if IS_DEV:
        print("\n  💡 To run production training:")
        print("     Windows:    set EAGLEEYE_MODE=prod")
        print("     Linux/Mac:  export EAGLEEYE_MODE=prod")
        print("     Railway:    Set EAGLEEYE_MODE=prod in env vars")

    train_dir = DATA_DIR / "train"
    val_dir = DATA_DIR / "val"

    if not train_dir.exists() or not any(train_dir.iterdir()):
        print(f"\n  ❌ Training data not found at {train_dir}")
        print("  Options:")
        print("    python -m ml.setup_training_data")
        print("    python -m ml.download_real_data")
        return

    # ── Detect data type ──
    real_count = _count_real_images(train_dir)
    total_files = sum(
        len(list(d.glob("*.*")))
        for d in train_dir.iterdir()
        if d.is_dir()
    )
    is_real = real_count > total_files * 0.3
    data_type = "REAL satellite" if is_real else "SYNTHETIC"

    print(f"\n  📊 Data type: {data_type}")
    print(f"     Real images: {real_count}, Total: {total_files}")

    train_tf, val_tf = get_transforms(is_real=is_real)

    train_ds = datasets.ImageFolder(train_dir, transform=train_tf)
    val_ds = datasets.ImageFolder(val_dir, transform=val_tf)

    if len(train_ds) == 0:
        print("  ❌ No training images found.")
        return

    num_workers = 0 if os.name == "nt" else 2

    # ── Weighted sampling for class balance ──
    class_weights = _get_class_weights(train_ds)
    sample_weights = [
        float(class_weights[label]) for _, label in train_ds
    ]
    sampler = WeightedRandomSampler(sample_weights, len(train_ds))

    # Detect if GPU is available for pin_memory
    use_pin_memory = torch.cuda.is_available()

    train_loader = DataLoader(
        train_ds,
        batch_size=BATCH_SIZE,
        sampler=sampler,
        num_workers=num_workers,
        pin_memory=use_pin_memory,
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=use_pin_memory,
    )

    print(f"\n  ── Configuration ──")
    print(f"  Training samples:   {len(train_ds)}")
    print(f"  Validation samples: {len(val_ds)}")
    print(f"  Classes:            {train_ds.classes}")
    class_dist = [
        sum(1 for _, l in train_ds if l == i) for i in range(NUM_CLASSES)
    ]
    print(f"  Class distribution: {class_dist}")
    print(f"  Class weights:      {[round(w, 4) for w in class_weights.tolist()]}")
    print(f"  GPU available:      {torch.cuda.is_available()}")
    print(f"  Batch size:         {BATCH_SIZE} (effective: {BATCH_SIZE * GRAD_ACCUMULATION})")
    print(f"  Stage 1 epochs:     {EPOCHS_STAGE1}")
    print(f"  Stage 2 epochs:     {EPOCHS_STAGE2}")
    print(f"  Patience:           {PATIENCE}")
    print(f"  Weight decay:       {WEIGHT_DECAY}")

    # ── Build model ──
    from ml.detector import CampDetector
    detector = CampDetector()

    if detector.model is None:
        print("  ❌ Failed to build model.")
        return

    model = detector.model
    device = detector.device
    assert device is not None

    # Loss with label smoothing
    criterion = nn.CrossEntropyLoss(
        weight=class_weights.to(device),
        label_smoothing=LABEL_SMOOTHING,
    )

    # EMA model
    ema = ModelEMA(model, decay=EMA_DECAY)

    best_val_acc = 0.0
    best_ema_val_acc = 0.0
    patience_counter = 0
    history: list[dict[str, Any]] = []
    global_step = 0
    training_start = time.time()

    # ════════════════════════════════════════════════════
    # STAGE 1: Frozen backbone — train classifier head
    # ════════════════════════════════════════════════════
    print(f"\n  ══ Stage 1: Frozen Backbone ({EPOCHS_STAGE1} epochs) ══")
    print("  Training classifier head only (fast convergence)")
    print(f"  Head LR: {LR_HEAD}, Weight Decay: {WEIGHT_DECAY}")
    print(f"  Mix probability: {MIX_PROBABILITY_S1}")

    detector.freeze_backbone()

    head_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = optim.AdamW(
        head_params, lr=LR_HEAD, weight_decay=WEIGHT_DECAY
    )

    # Smooth cosine decay — NO warm restarts
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=EPOCHS_STAGE1, eta_min=LR_MIN
    )

    print(
        f"\n  {'Epoch':>5} | {'Loss':>8} | {'Train':>7} | "
        f"{'Val':>7} | {'EMA':>7} | {'LR':>10} | {'Time':>5}"
    )
    print(f"  {'─' * 65}")

    for epoch in range(1, EPOCHS_STAGE1 + 1):
        epoch_start = time.time()

        avg_loss, train_acc, steps = _train_one_epoch(
            model=model,
            train_loader=train_loader,
            criterion=criterion,
            optimizer=optimizer,
            ema=ema,
            device=device,
            mix_probability=MIX_PROBABILITY_S1,
        )
        global_step += steps

        scheduler.step()

        # ── Validate ──
        _, val_acc = _validate(model, val_loader, criterion, device)
        _, ema_val_acc = _validate(
            ema.ema_model, val_loader, criterion, device
        )

        current_lr = float(optimizer.param_groups[0]["lr"])
        elapsed = time.time() - epoch_start

        # ── Checkpointing ──
        marker = ""
        effective_acc = max(val_acc, ema_val_acc)
        if effective_acc > best_val_acc:
            best_val_acc = effective_acc
            patience_counter = 0
            if ema_val_acc >= val_acc:
                WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
                torch.save(
                    ema.state_dict(),
                    WEIGHTS_DIR / "camp_detector_v1.pt",
                )
                marker = " ✓ EMA"
                best_ema_val_acc = ema_val_acc
            else:
                detector.save_weights()
                marker = " ✓ saved"
        else:
            patience_counter += 1

        history.append({
            "stage": 1,
            "epoch": epoch,
            "loss": round(avg_loss, 4),
            "train_acc": round(train_acc, 4),
            "val_acc": round(val_acc, 4),
            "ema_val_acc": round(ema_val_acc, 4),
            "lr": round(current_lr, 8),
        })

        print(
            f"  {epoch:5d} | {avg_loss:8.4f} | {train_acc:6.1%} | "
            f"{val_acc:6.1%} | {ema_val_acc:6.1%} | "
            f"{current_lr:10.2e} | {elapsed:4.1f}s{marker}"
        )

        # Early stopping in Stage 1 too (mainly for dev mode)
        if patience_counter >= PATIENCE:
            print(
                f"\n  ⚠️  Early stopping Stage 1 at epoch {epoch} "
                f"(no improvement for {PATIENCE} epochs)"
            )
            break

    stage1_best = best_val_acc
    print(f"\n  Stage 1 best: {stage1_best:.1%}")

    # ════════════════════════════════════════════════════
    # STAGE 2: Full fine-tuning with discriminative LR
    # v2.1: CosineAnnealingLR (no restarts), explicit LRs
    # ════════════════════════════════════════════════════
    print(f"\n  ══ Stage 2: Full Fine-tuning ({EPOCHS_STAGE2} epochs) ══")
    print("  Unfreezing backbone with discriminative learning rates")
    print(f"  Backbone LR: {LR_BACKBONE_S2}, Head LR: {LR_HEAD_S2}")
    print(f"  Weight Decay: {WEIGHT_DECAY}, Mix probability: {MIX_PROBABILITY_S2}")

    detector.unfreeze_backbone()

    # Explicit discriminative learning rates
    param_groups = detector.get_parameter_groups(
        backbone_lr=LR_BACKBONE_S2,
        head_lr=LR_HEAD_S2,
    )
    optimizer = optim.AdamW(
        param_groups, weight_decay=WEIGHT_DECAY
    )

    # FIXED: Smooth cosine decay — NO warm restarts
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=EPOCHS_STAGE2, eta_min=LR_MIN
    )

    # Reset EMA with current model state
    ema = ModelEMA(model, decay=EMA_DECAY)
    patience_counter = 0

    print(
        f"\n  {'Epoch':>5} | {'Loss':>8} | {'Train':>7} | "
        f"{'Val':>7} | {'EMA':>7} | {'BB LR':>10} | "
        f"{'HD LR':>10} | {'Time':>5}"
    )
    print(f"  {'─' * 80}")

    for epoch in range(1, EPOCHS_STAGE2 + 1):
        epoch_start = time.time()

        avg_loss, train_acc, steps = _train_one_epoch(
            model=model,
            train_loader=train_loader,
            criterion=criterion,
            optimizer=optimizer,
            ema=ema,
            device=device,
            mix_probability=MIX_PROBABILITY_S2,
        )
        global_step += steps

        scheduler.step()

        # ── Validate ──
        _, val_acc = _validate(model, val_loader, criterion, device)
        _, ema_val_acc = _validate(
            ema.ema_model, val_loader, criterion, device
        )

        bb_lr = float(optimizer.param_groups[0]["lr"])
        hd_lr = float(optimizer.param_groups[1]["lr"])
        elapsed = time.time() - epoch_start

        # ── Checkpointing ──
        marker = ""
        effective_acc = max(val_acc, ema_val_acc)
        if effective_acc > best_val_acc:
            best_val_acc = effective_acc
            patience_counter = 0
            if ema_val_acc >= val_acc:
                WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
                torch.save(
                    ema.state_dict(),
                    WEIGHTS_DIR / "camp_detector_v1.pt",
                )
                marker = " ✓ EMA"
                best_ema_val_acc = ema_val_acc
            else:
                detector.save_weights()
                marker = " ✓ saved"
        else:
            patience_counter += 1

        history.append({
            "stage": 2,
            "epoch": EPOCHS_STAGE1 + epoch,
            "loss": round(avg_loss, 4),
            "train_acc": round(train_acc, 4),
            "val_acc": round(val_acc, 4),
            "ema_val_acc": round(ema_val_acc, 4),
            "lr_backbone": round(bb_lr, 8),
            "lr_head": round(hd_lr, 8),
        })

        print(
            f"  {EPOCHS_STAGE1 + epoch:5d} | {avg_loss:8.4f} | "
            f"{train_acc:6.1%} | {val_acc:6.1%} | {ema_val_acc:6.1%} | "
            f"{bb_lr:10.2e} | {hd_lr:10.2e} | {elapsed:4.1f}s{marker}"
        )

        if patience_counter >= PATIENCE:
            print(
                f"\n  ⚠️  Early stopping at epoch "
                f"{EPOCHS_STAGE1 + epoch} "
                f"(no improvement for {PATIENCE} epochs)"
            )
            break

    # ════════════════════════════════════════════════════
    # FINAL EVALUATION
    # Dev:  Standard accuracy only (fast)
    # Prod: Full TTA evaluation
    # ════════════════════════════════════════════════════
    tta_label = "TTA Accuracy" if not IS_DEV else "Final Accuracy (no TTA in dev)"
    print(f"\n  ── Final Evaluation ──")

    best_weights_path = WEIGHTS_DIR / "camp_detector_v1.pt"
    if best_weights_path.exists():
        model.load_state_dict(
            torch.load(
                best_weights_path,
                map_location=device,
                weights_only=True,
            )
        )

    tta_acc = _validate_with_tta(model, val_loader, device)
    print(f"  {tta_label}: {tta_acc:.1%}")

    # ── Training time summary ──
    total_time = time.time() - training_start
    time_min = total_time / 60

    # ── Save training log ──
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "training_log.json"

    final_epoch = len(history)
    log_data: dict[str, Any] = {
        "version": "2.1",
        "mode": "dev" if IS_DEV else "prod",
        "epochs_run": final_epoch,
        "epochs_stage1": EPOCHS_STAGE1,
        "epochs_stage2": EPOCHS_STAGE2,
        "batch_size": BATCH_SIZE,
        "effective_batch_size": BATCH_SIZE * GRAD_ACCUMULATION,
        "lr_head_s1": LR_HEAD,
        "lr_backbone_s2": LR_BACKBONE_S2,
        "lr_head_s2": LR_HEAD_S2,
        "weight_decay": WEIGHT_DECAY,
        "label_smoothing": LABEL_SMOOTHING,
        "mixup_alpha": MIXUP_ALPHA,
        "cutmix_alpha": CUTMIX_ALPHA,
        "mix_probability_s1": MIX_PROBABILITY_S1,
        "mix_probability_s2": MIX_PROBABILITY_S2,
        "ema_decay": EMA_DECAY,
        "stage1_best_val_acc": round(stage1_best, 4),
        "best_val_acc": round(best_val_acc, 4),
        "best_ema_val_acc": round(best_ema_val_acc, 4),
        "tta_val_acc": round(tta_acc, 4),
        "training_time_minutes": round(time_min, 1),
        "data_type": data_type,
        "real_images": real_count,
        "total_images": total_files,
        "history": history,
        "classes": train_ds.classes,
        "train_samples": len(train_ds),
        "val_samples": len(val_ds),
        "gpu": torch.cuda.is_available(),
        "scheduler": "CosineAnnealingLR",
    }

    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2)

    print(f"\n  {'=' * 60}")
    print(f"  ✅ Training complete!")
    print(f"  ✅ Mode:                         {'DEV' if IS_DEV else 'PROD'}")
    print(f"  ✅ Training time:                 {time_min:.1f} minutes")
    print(f"  ✅ Stage 1 best val accuracy:     {stage1_best:.1%}")
    print(f"  ✅ Best validation accuracy:      {best_val_acc:.1%}")
    print(f"  ✅ Best EMA validation accuracy:  {best_ema_val_acc:.1%}")
    print(f"  ✅ {tta_label}:  {tta_acc:.1%}")
    print(f"  ✅ Data type: {data_type}")
    print(f"  ✅ Weights: {WEIGHTS_DIR / 'camp_detector_v1.pt'}")
    print(f"  ✅ Log: {log_path}")

    if IS_DEV:
        print(f"\n  💡 For production accuracy, run:")
        print(f"     set EAGLEEYE_MODE=prod && python -m ml.train")

    print(f"  {'=' * 60}")


if __name__ == "__main__":
    train()