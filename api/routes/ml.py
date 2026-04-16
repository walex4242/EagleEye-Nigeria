"""
ml.py
──────
API routes for ML-based satellite image analysis.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
import traceback
import io

router = APIRouter()


@router.post("/ml/predict")
async def predict_image(
    file: UploadFile = File(..., description="Satellite image patch (JPEG/PNG)"),
):
    """
    Run CampDetector inference on an uploaded satellite image patch.
    Returns classification (legal_activity vs suspicious_encampment) with confidence.
    """
    try:
        from ml.detector import CampDetector, TORCH_AVAILABLE
        from ml.preprocessor import preprocess_image, TORCH_AVAILABLE as PREPROCESS_AVAILABLE

        if not TORCH_AVAILABLE or not PREPROCESS_AVAILABLE:
            return {
                "status": "unavailable",
                "message": "PyTorch is not installed. ML inference is disabled.",
                "mock_result": {
                    "label": "legal_activity",
                    "confidence": 0.0,
                    "flag": False,
                    "class_id": 0,
                },
            }

        from PIL import Image
        import numpy as np

        # Read uploaded image
        contents = await file.read()
        image = Image.open(io.BytesIO(contents)).convert("RGB")
        image_array = np.array(image)

        # Preprocess
        tensor = preprocess_image(image_array)
        if tensor is None:
            raise ValueError("Preprocessing failed — returned None.")

        # Predict
        detector = CampDetector()
        result = detector.predict(tensor)

        return {
            "status": "success",
            "filename": file.filename,
            "result": result,
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /ml/predict failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ml/predict-batch")
async def predict_batch(
    files: list[UploadFile] = File(..., description="Multiple satellite image patches"),
):
    """
    Run CampDetector on multiple uploaded images.
    """
    try:
        from ml.detector import CampDetector, TORCH_AVAILABLE
        from ml.preprocessor import preprocess_image

        if not TORCH_AVAILABLE:
            return {
                "status": "unavailable",
                "message": "PyTorch is not installed.",
            }

        from PIL import Image
        import numpy as np

        detector = CampDetector()
        results = []

        for file in files:
            contents = await file.read()
            image = Image.open(io.BytesIO(contents)).convert("RGB")
            image_array = np.array(image)
            tensor = preprocess_image(image_array)

            if tensor is not None:
                result = detector.predict(tensor)
                results.append({
                    "filename": file.filename,
                    "result": result,
                })
            else:
                results.append({
                    "filename": file.filename,
                    "error": "Preprocessing failed",
                })

        flagged = sum(1 for r in results if r.get("result", {}).get("flag", False))

        return {
            "status": "success",
            "total": len(results),
            "flagged": flagged,
            "results": results,
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /ml/predict-batch failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ml/status")
def ml_status():
    """
    Check ML model availability and configuration.
    """
    status = {
        "torch_available": False,
        "model_loaded": False,
        "weights_found": False,
        "device": "cpu",
    }

    try:
        from ml.detector import CampDetector, TORCH_AVAILABLE, WEIGHTS_PATH

        status["torch_available"] = TORCH_AVAILABLE
        status["weights_found"] = WEIGHTS_PATH.exists()

        if TORCH_AVAILABLE:
            import torch
            status["device"] = "cuda" if torch.cuda.is_available() else "cpu"
            status["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                status["gpu_name"] = torch.cuda.get_device_name(0)

            # Try loading the model
            detector = CampDetector()
            status["model_loaded"] = detector.model is not None

    except Exception as e:
        status["error"] = str(e)

    return status