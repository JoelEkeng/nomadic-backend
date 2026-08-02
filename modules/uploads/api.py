"""Minimal file upload endpoint for onboarding documents.

Files are stored on disk under ``uploads/`` and served statically by the app.
This is intentionally simple for MVP; swap in object storage for production.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(request: Request, file: UploadFile = File(...)) -> dict[str, str]:
    """Upload a file and return a public URL that can be submitted to KYC."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    extension = Path(file.filename).suffix.lower() or ".bin"
    allowed = {".jpg", ".jpeg", ".png", ".pdf", ".webp", ".bin"}
    if extension not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {extension}",
        )

    file_id = f"{uuid.uuid4().hex}{extension}"
    file_path = UPLOAD_DIR / file_id

    try:
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large (max 10MB)",
            )
        file_path.write_bytes(contents)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save uploaded file",
        ) from exc
    finally:
        await file.close()

    base_url = str(request.base_url).rstrip("/")
    return {
        "file_id": file_id,
        "url": f"{base_url}/uploads/{file_id}",
        "filename": file.filename,
    }
