"""
preprocessor.py
────────────────
Prepares satellite image patches for input to the CampDetector model.

Pipeline:
  1. Load image (file path, numpy array, or PIL Image)
  2. Resize to model input size (224x224)
  3. Normalize pixel values to [0, 1] via ToTensor
  4. Apply ImageNet mean/std normalisation
  5. Return batch-ready tensor [1, 3, 224, 224]

Supports multi-scale patch extraction for scanning large images.
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


def preprocess_for_tta(
    source: str | np.ndarray | Image.Image,
    size: int = MODEL_INPUT_SIZE,
) -> list[torch.Tensor] | None:
    """
    Create multiple augmented versions for test-time augmentation.

    Returns a list of tensors (original + augmented views) that can
    be individually passed to the model and averaged.

    Args:
        source: File path (str), PIL Image, or numpy array (H, W, C).
        size:   Target square size in pixels (default 224).

    Returns:
        List of torch.Tensor, each of shape [1, 3, size, size].
        Returns None if PyTorch is not available.
    """
    if not TORCH_AVAILABLE:
        print("Warning: PyTorch not available. Returning None.")
        return None

    base_normalize = T.Compose([
        T.Resize((size, size)),
        T.ToTensor(),
        T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])

    tta_transforms = [
        # Original
        T.Compose([
            T.Resize((size, size)),
            T.ToTensor(),
            T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]),
        # Horizontal flip
        T.Compose([
            T.Resize((size, size)),
            T.RandomHorizontalFlip(p=1.0),
            T.ToTensor(),
            T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]),
        # Vertical flip
        T.Compose([
            T.Resize((size, size)),
            T.RandomVerticalFlip(p=1.0),
            T.ToTensor(),
            T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]),
        # Slight zoom (center crop from larger resize)
        T.Compose([
            T.Resize((int(size * 1.1), int(size * 1.1))),
            T.CenterCrop(size),
            T.ToTensor(),
            T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]),
        # 90-degree rotation
        T.Compose([
            T.Resize((size, size)),
            T.RandomRotation(degrees=(90, 90)),
            T.ToTensor(),
            T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]),
        # 180-degree rotation
        T.Compose([
            T.Resize((size, size)),
            T.RandomRotation(degrees=(180, 180)),
            T.ToTensor(),
            T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]),
        # 270-degree rotation
        T.Compose([
            T.Resize((size, size)),
            T.RandomRotation(degrees=(270, 270)),
            T.ToTensor(),
            T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]),
    ]

    # Load image
    image: Image.Image
    if isinstance(source, str):
        image = Image.open(source).convert("RGB")
    elif isinstance(source, np.ndarray):
        image = Image.fromarray(source.astype(np.uint8)).convert("RGB")
    elif isinstance(source, Image.Image):
        image = source.convert("RGB")
    else:
        raise ValueError(f"Unsupported source type: {type(source)}")

    tensors: list[torch.Tensor] = []
    for tf in tta_transforms:
        t = tf(image)
        assert isinstance(t, torch.Tensor)
        tensors.append(t.unsqueeze(0))

    return tensors


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


def extract_multiscale_patches(
    image_array: np.ndarray,
    scales: list[int] | None = None,
    stride_ratio: float = 0.5,
) -> list[dict[str, Any]]:
    """
    Extract patches at multiple scales for more robust detection.

    Large-scale patches capture context (camp + surroundings),
    small-scale patches capture fine detail (individual structures).

    Args:
        image_array: numpy array of shape (H, W, C).
        scales:      List of patch sizes. Default: [160, 224, 320].
        stride_ratio: Stride as fraction of patch size.

    Returns:
        List of dicts: {
            'patch': tensor (resized to 224x224),
            'row': int,
            'col': int,
            'scale': int (original patch size)
        }
    """
    if not TORCH_AVAILABLE:
        return []

    if scales is None:
        scales = [160, 224, 320]

    h, w = image_array.shape[:2]
    all_patches: list[dict[str, Any]] = []

    for scale in scales:
        if scale > h or scale > w:
            continue

        stride = max(1, int(scale * stride_ratio))

        for row in range(0, h - scale + 1, stride):
            for col in range(0, w - scale + 1, stride):
                patch_arr = image_array[
                    row:row + scale, col:col + scale
                ]
                # Always resize to model input size
                tensor = preprocess_image(patch_arr, size=MODEL_INPUT_SIZE)
                all_patches.append({
                    "patch": tensor,
                    "row": row,
                    "col": col,
                    "scale": scale,
                })

    return all_patches


def denormalize_tensor(tensor: torch.Tensor) -> np.ndarray:
    """
    Convert a normalized tensor back to a displayable numpy array.
    Useful for debugging and visualization.

    Args:
        tensor: torch.Tensor of shape [1, 3, H, W] or [3, H, W]

    Returns:
        numpy array of shape (H, W, 3) with values in [0, 255]
    """
    if not TORCH_AVAILABLE:
        return np.zeros((224, 224, 3), dtype=np.uint8)

    if tensor.dim() == 4:
        tensor = tensor.squeeze(0)

    mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD).view(3, 1, 1)

    tensor = tensor.cpu().clone()
    tensor = tensor * std + mean
    tensor = torch.clamp(tensor, 0.0, 1.0)

    # Convert CHW -> HWC
    arr = tensor.permute(1, 2, 0).numpy()
    arr = (arr * 255).astype(np.uint8)
    return arr