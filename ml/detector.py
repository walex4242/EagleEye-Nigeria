"""
detector.py
────────────
CampDetector: A CNN-based binary classifier that distinguishes between:
  - Class 0: Legal activity (farmland, villages, cleared fields)
  - Class 1: Suspicious encampment (irregular structures, hidden clearings)

Architecture: Fine-tuned EfficientNet-B0 with pretrained ImageNet weights,
custom classifier head with dropout regularization, and optional
test-time augmentation (TTA) for high-confidence predictions.

Phase 3 deliverable — model weights are saved to ml/weights/ after training.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

TORCH_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torchvision.models as models
    import torchvision.transforms as T
    TORCH_AVAILABLE = True
except ImportError:
    pass

if TYPE_CHECKING:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torchvision.models as models
    import torchvision.transforms as T

WEIGHTS_DIR = Path(__file__).parent / "weights"
WEIGHTS_PATH = WEIGHTS_DIR / "camp_detector_v1.pt"

LABELS = {0: "legal_activity", 1: "suspicious_encampment"}
CONFIDENCE_THRESHOLD = 0.75

# ImageNet normalization
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class SpatialAttention(nn.Module):
    """Lightweight spatial attention module to focus on camp-like regions."""

    def __init__(self, kernel_size: int = 7):
        super().__init__()
        padding = kernel_size // 2
        self.conv = nn.Conv2d(2, 1, kernel_size, padding=padding, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        avg_out = torch.mean(x, dim=1, keepdim=True)
        max_out, _ = torch.max(x, dim=1, keepdim=True)
        combined = torch.cat([avg_out, max_out], dim=1)
        attention = self.sigmoid(self.conv(combined))
        return x * attention


class ClassifierHead(nn.Module):
    """
    Custom classifier head with:
    - Global average + max pooling concatenation
    - BatchNorm + Dropout for regularization
    - Two FC layers with GELU activation
    - Two-class output for binary classification

    v2.1: Increased dropout rates to combat overfitting.
    """

    def __init__(self, in_features: int, dropout: float = 0.5):
        super().__init__()
        # Concatenating avg + max pool doubles features
        combined_features = in_features * 2

        self.attention = SpatialAttention()
        self.bn0 = nn.BatchNorm1d(combined_features)
        self.dropout1 = nn.Dropout(p=dropout)
        self.fc1 = nn.Linear(combined_features, 512)
        self.bn1 = nn.BatchNorm1d(512)
        self.gelu = nn.GELU()
        self.dropout2 = nn.Dropout(p=dropout)
        self.fc2 = nn.Linear(512, 128)
        self.bn2 = nn.BatchNorm1d(128)
        self.dropout3 = nn.Dropout(p=dropout * 0.6)
        self.fc3 = nn.Linear(128, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x is feature map from backbone: [B, C, H, W]
        x = self.attention(x)

        # Dual pooling
        avg_pool = F.adaptive_avg_pool2d(x, 1).flatten(1)
        max_pool = F.adaptive_max_pool2d(x, 1).flatten(1)
        x = torch.cat([avg_pool, max_pool], dim=1)

        x = self.bn0(x)
        x = self.dropout1(x)
        x = self.gelu(self.fc1(x))
        x = self.bn1(x)
        x = self.dropout2(x)
        x = self.gelu(self.fc2(x))
        x = self.bn2(x)
        x = self.dropout3(x)
        x = self.fc3(x)
        return x


class CampDetector:
    """
    Satellite image patch classifier for detecting suspicious encampments.

    Key improvements over v0:
    - EfficientNet-B0 backbone with pretrained ImageNet weights
    - Custom classifier head with spatial attention
    - Dual pooling (avg + max) for richer feature aggregation
    - Test-time augmentation (TTA) for high-confidence predictions
    - Proper two-stage fine-tuning support (freeze then unfreeze backbone)
    - Graceful handling of architecture-mismatched weight files

    v2.1: Fixed discriminative LR ratios, increased dropout.
    """

    def __init__(self, weights_path: str | Path | None = None):
        if not TORCH_AVAILABLE:
            print(
                "Warning: PyTorch not available. "
                "CampDetector running in mock mode."
            )
            self.model = None
            self.device = None
            self._tta_transforms = None
            return

        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        self.model = self._build_model()
        self._tta_transforms = self._build_tta_transforms()

        path = Path(weights_path) if weights_path else WEIGHTS_PATH
        if path.exists():
            try:
                state_dict = torch.load(
                    path, map_location=self.device, weights_only=True
                )
                self.model.load_state_dict(state_dict)
                print(f"Loaded weights from {path}")
            except RuntimeError as e:
                print(
                    f"⚠️  Could not load weights from {path} "
                    f"(architecture mismatch). Starting fresh."
                )
                print(f"   Detail: {str(e)[:150]}...")
                print(
                    f"   Delete the old file and retrain: "
                    f"del {path}"
                )
        else:
            print(
                f"No weights found at {path}. "
                "Model running with pretrained backbone — "
                "train before use in production."
            )

        self.model.eval()

    def _build_model(self) -> nn.Module:
        """
        Build EfficientNet-B0 with pretrained weights and custom head.

        EfficientNet-B0 advantages over MobileNetV3-Small:
        - Better accuracy/compute tradeoff
        - Compound scaling
        - Still lightweight enough for field deployment
        """
        try:
            # Try loading with new API (torchvision >= 0.13)
            efficientnet_weights = models.EfficientNet_B0_Weights.IMAGENET1K_V1
            backbone = models.efficientnet_b0(weights=efficientnet_weights)
        except AttributeError:
            # Fallback for older torchvision
            backbone = models.efficientnet_b0(pretrained=True)

        # EfficientNet-B0 last conv outputs 1280 channels
        feature_dim = 1280

        # Keep only the feature extractor (conv layers)
        backbone_features = backbone.features

        # Build complete model
        model = _CampDetectorModel(backbone_features, feature_dim)

        assert self.device is not None
        return model.to(self.device)

    def _build_tta_transforms(self) -> list[T.Compose]:
        """Build test-time augmentation transforms."""
        base_normalize = T.Normalize(IMAGENET_MEAN, IMAGENET_STD)

        transforms_list = [
            # Original
            T.Compose([
                T.Resize((224, 224)),
                T.ToTensor(),
                base_normalize,
            ]),
            # Horizontal flip
            T.Compose([
                T.Resize((224, 224)),
                T.RandomHorizontalFlip(p=1.0),
                T.ToTensor(),
                base_normalize,
            ]),
            # Vertical flip
            T.Compose([
                T.Resize((224, 224)),
                T.RandomVerticalFlip(p=1.0),
                T.ToTensor(),
                base_normalize,
            ]),
            # Slight zoom
            T.Compose([
                T.Resize((240, 240)),
                T.CenterCrop(224),
                T.ToTensor(),
                base_normalize,
            ]),
            # Rotation 90
            T.Compose([
                T.Resize((224, 224)),
                T.RandomRotation(degrees=(90, 90)),
                T.ToTensor(),
                base_normalize,
            ]),
        ]
        return transforms_list

    def freeze_backbone(self) -> None:
        """Freeze backbone for initial training of classifier head only."""
        if self.model is None:
            return
        assert isinstance(self.model, _CampDetectorModel)
        for param in self.model.backbone.parameters():
            param.requires_grad = False
        print("Backbone frozen — training classifier head only.")

    def unfreeze_backbone(self, lr_multiplier: float = 0.1) -> None:
        """
        Unfreeze backbone for full fine-tuning.
        """
        if self.model is None:
            return
        assert isinstance(self.model, _CampDetectorModel)
        for param in self.model.backbone.parameters():
            param.requires_grad = True
        print(
            f"Backbone unfrozen — use {lr_multiplier}x LR "
            "for backbone params."
        )

    def get_parameter_groups(
        self, backbone_lr: float, head_lr: float
    ) -> list[dict[str, Any]]:
        """
        Get parameter groups with discriminative learning rates.

        Args:
            backbone_lr: Learning rate for pretrained backbone layers.
            head_lr:     Learning rate for classifier head layers.

        Returns:
            List of param group dicts for optimizer.

        v2.1: Takes explicit LRs instead of computing ratio internally.
              This prevents the confusing 0.1 * 0.1 = 0.01x issue.
        """
        if self.model is None:
            return []

        assert isinstance(self.model, _CampDetectorModel)
        return [
            {
                "params": self.model.backbone.parameters(),
                "lr": backbone_lr,
                "name": "backbone",
            },
            {
                "params": self.model.head.parameters(),
                "lr": head_lr,
                "name": "head",
            },
        ]

    def predict(
        self, tensor: torch.Tensor, use_tta: bool = False
    ) -> dict[str, Any]:
        """
        Run inference on a preprocessed image tensor.

        Args:
            tensor: torch.Tensor of shape [1, 3, 224, 224]
            use_tta: If True, use test-time augmentation for
                     higher accuracy (5x slower).

        Returns:
            dict with label, confidence, flag, class_id
        """
        if not TORCH_AVAILABLE or self.model is None:
            return self._mock_prediction()

        self.model.eval()

        with torch.no_grad():
            if use_tta and self._tta_transforms is not None:
                return self._predict_with_tta(tensor)

            tensor = tensor.to(self.device)
            logits = self.model(tensor)
            probs = torch.softmax(logits, dim=1)
            class_id = int(torch.argmax(probs, dim=1).item())
            confidence = float(probs[0][class_id].item())

        return {
            "label": LABELS[class_id],
            "confidence": round(confidence, 4),
            "flag": class_id == 1 and confidence >= CONFIDENCE_THRESHOLD,
            "class_id": class_id,
        }

    def _predict_with_tta(self, tensor: torch.Tensor) -> dict[str, Any]:
        """
        Test-time augmentation: run multiple augmented versions
        and average the predictions.
        """
        assert self.model is not None
        assert self.device is not None

        all_probs: list[torch.Tensor] = []

        # Original
        logits = self.model(tensor.to(self.device))
        all_probs.append(torch.softmax(logits, dim=1))

        # Horizontal flip
        flipped_h = torch.flip(tensor, dims=[3])
        logits = self.model(flipped_h.to(self.device))
        all_probs.append(torch.softmax(logits, dim=1))

        # Vertical flip
        flipped_v = torch.flip(tensor, dims=[2])
        logits = self.model(flipped_v.to(self.device))
        all_probs.append(torch.softmax(logits, dim=1))

        # Both flips
        flipped_both = torch.flip(tensor, dims=[2, 3])
        logits = self.model(flipped_both.to(self.device))
        all_probs.append(torch.softmax(logits, dim=1))

        # Transpose (90° rotation equivalent for square images)
        transposed = tensor.permute(0, 1, 3, 2)
        logits = self.model(transposed.to(self.device))
        all_probs.append(torch.softmax(logits, dim=1))

        # Average all predictions
        avg_probs = torch.stack(all_probs).mean(dim=0)
        class_id = int(torch.argmax(avg_probs, dim=1).item())
        confidence = float(avg_probs[0][class_id].item())

        return {
            "label": LABELS[class_id],
            "confidence": round(confidence, 4),
            "flag": class_id == 1 and confidence >= CONFIDENCE_THRESHOLD,
            "class_id": class_id,
            "tta": True,
            "num_augments": len(all_probs),
        }

    def predict_batch(
        self, tensors: list[torch.Tensor], use_tta: bool = False
    ) -> list[dict[str, Any]]:
        """Run predict() on a list of tensors."""
        return [self.predict(t, use_tta=use_tta) for t in tensors]

    def save_weights(self, path: str | Path | None = None) -> None:
        """Save current model weights to disk."""
        if not TORCH_AVAILABLE or self.model is None:
            print("Cannot save weights — model not available.")
            return
        save_path = Path(path) if path else WEIGHTS_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), save_path)
        print(f"Weights saved to {save_path}")

    @staticmethod
    def _mock_prediction() -> dict[str, Any]:
        """Fallback prediction when PyTorch is unavailable."""
        return {
            "label": "legal_activity",
            "confidence": 0.0,
            "flag": False,
            "class_id": 0,
            "note": "Mock result — PyTorch not available",
        }


class _CampDetectorModel(nn.Module):
    """
    Internal model combining EfficientNet backbone with custom head.
    Separated so we can cleanly save/load state_dict.
    """

    def __init__(self, backbone: nn.Module, feature_dim: int):
        super().__init__()
        self.backbone = backbone
        self.head = ClassifierHead(feature_dim, dropout=0.5)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.backbone(x)  # [B, 1280, 7, 7]
        return self.head(features)