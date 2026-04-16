"""
preprocessor.py
────────────────
Prepares satellite image patches for input to the CampDetector model.

Pipeline:
  1. Load image (file path or numpy array)
  2. Resize to model input size (224x224)
  3. Normalize pixel values to [0, 1]
  4. Convert to PyTorch tensor [C, H, W]
  5. Apply ImageNet mean/std normalisation

Used in Phase 3: AI classification of encampments vs. legal activity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

TORCH_AVAILABLE = False

try:
    import numpy as np
    import torch
    import torchvision.transforms as T
    from PIL import Image
    TORCH_AVAILABLE = True
except ImportError:
    pass

if TYPE_CHECKING:
    import numpy as np
    import torch
    import torchvision.transforms as T
    from PIL import Image

# Standard ImageNet normalisation values
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

MODEL_INPUT_SIZE = 224


def preprocess_image(
    source: str | np.ndarray | Image.Image,
    size: int = MODEL_INPUT_SIZE,
) -> torch.Tensor | None:
    """
    Load and preprocess a satellite image patch for model inference.

    Args:
        source: File path (str), PIL Image, or numpy array (H, W, C).
        size:   Target square size in pixels (default 224).

    Returns:
        torch.Tensor of shape [1, 3, size, size] ready for model input.
        Returns None if PyTorch is not available.

    Raises:
        ValueError: If source type is not supported.
        FileNotFoundError: If file path does not exist.
    """
    if not TORCH_AVAILABLE:
        print("Warning: PyTorch not available. Returning None.")
        return None

    transform = T.Compose([
        T.Resize((size, size)),
        T.ToTensor(),
        T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])

    image: Image.Image

    if isinstance(source, str):
        image = Image.open(source).convert("RGB")
    elif isinstance(source, np.ndarray):
        image = Image.fromarray(source.astype(np.uint8)).convert("RGB")
    elif isinstance(source, Image.Image):
        image = source.convert("RGB")
    else:
        raise ValueError(f"Unsupported source type: {type(source)}")

    transformed = transform(image)
    assert isinstance(transformed, torch.Tensor)
    tensor = transformed.unsqueeze(0)  # [1, C, H, W]
    return tensor


def extract_patches(
    image_array: np.ndarray,
    patch_size: int = 224,
    stride: int = 112,
) -> list[dict[str, Any]]:
    """
    Slide a window over a large satellite image and extract patches.

    Args:
        image_array: numpy array of shape (H, W, C).
        patch_size:  Size of each square patch in pixels.
        stride:      Step size between patches (overlap = patch_size - stride).

    Returns:
        List of dicts: {'patch': tensor, 'row': int, 'col': int}
    """
    if not TORCH_AVAILABLE:
        return []

    h, w = image_array.shape[:2]
    patches: list[dict[str, Any]] = []

    for row in range(0, h - patch_size + 1, stride):
        for col in range(0, w - patch_size + 1, stride):
            patch = image_array[row:row + patch_size, col:col + patch_size]
            tensor = preprocess_image(patch, size=patch_size)
            patches.append({"patch": tensor, "row": row, "col": col})

    return patches