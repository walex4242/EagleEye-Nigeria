"""
detector.py
────────────
CampDetector: A CNN-based binary classifier that distinguishes between:
  - Class 0: Legal activity (farmland, villages, cleared fields)
  - Class 1: Suspicious encampment (irregular structures, hidden clearings)

Architecture: Fine-tuned MobileNetV3-Small (lightweight, deployable on
low-resource field hardware).

Phase 3 deliverable — model weights are saved to ml/weights/ after training.
"""

from __future__ import annotations
import os
import json
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import torch
    import torch.nn as nn
    import torchvision.models as models
    TORCH_AVAILABLE = True
except ImportError:
    torch = None   # type: ignore[assignment]
    nn = None      # type: ignore[assignment]
    models = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False

if TYPE_CHECKING:
    import torch
    import torch.nn as nn
    import torchvision.models as models

WEIGHTS_DIR = Path(__file__).parent / "weights"
WEIGHTS_PATH = WEIGHTS_DIR / "camp_detector_v1.pt"

LABELS = {0: "legal_activity", 1: "suspicious_encampment"}
CONFIDENCE_THRESHOLD = 0.65


class CampDetector:
    """
    Satellite image patch classifier for detecting suspicious encampments.
    """

    def __init__(self, weights_path: str | Path | None = None):
        if not TORCH_AVAILABLE or torch is None:
            print("Warning: PyTorch not available. CampDetector running in mock mode.")
            self.model = None
            self.device = None
            return

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = self._build_model()

        path = Path(weights_path) if weights_path else WEIGHTS_PATH
        if path.exists():
            self.model.load_state_dict(
                torch.load(path, map_location=self.device)
            )
            print(f"Loaded weights from {path}")
        else:
            print(
                f"No weights found at {path}. "
                "Model running with random weights — train before use in production."
            )

        self.model.eval()

    def _build_model(self) -> nn.Module:
        """Build MobileNetV3-Small with a binary output head."""
        assert torch is not None and nn is not None and models is not None

        model = models.mobilenet_v3_small(weights=None)

        # Type-narrow so Pylance knows classifier[3] is nn.Linear
        last_layer = model.classifier[3]
        assert isinstance(last_layer, nn.Linear)

        in_features: int = last_layer.in_features
        model.classifier[3] = nn.Linear(in_features, 2)

        assert self.device is not None
        return model.to(self.device)

    def predict(self, tensor: torch.Tensor) -> dict:
        """
        Run inference on a preprocessed image tensor.

        Args:
            tensor: torch.Tensor of shape [1, 3, 224, 224]

        Returns:
            dict with label, confidence, flag, class_id
        """
        if not TORCH_AVAILABLE or torch is None or self.model is None:
            return self._mock_prediction()

        with torch.no_grad():
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

    def predict_batch(self, tensors: list) -> list[dict]:
        """Run predict() on a list of tensors."""
        return [self.predict(t) for t in tensors]

    def save_weights(self, path: str | Path | None = None) -> None:
        """Save current model weights to disk."""
        if not TORCH_AVAILABLE or torch is None or self.model is None:
            print("Cannot save weights — model not available.")
            return
        save_path = Path(path) if path else WEIGHTS_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), save_path)
        print(f"Weights saved to {save_path}")

    @staticmethod
    def _mock_prediction() -> dict:
        """Fallback prediction when PyTorch is unavailable."""
        return {
            "label": "legal_activity",
            "confidence": 0.0,
            "flag": False,
            "class_id": 0,
            "note": "Mock result — PyTorch not available",
        }