import os
import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

_SHARED_SECRET = os.environ.get("API_SHARED_SECRET") or os.environ.get("GNAMMY_API_SHARED_SECRET") or ""

security = HTTPBearer(auto_error=False)


def require_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
    if not _SHARED_SECRET:
        logger.warning("require_auth: API_SHARED_SECRET/GNAMMY_API_SHARED_SECRET is not configured or empty.")
        return
    token = credentials.credentials if credentials else None
    if token != _SHARED_SECRET:
        logger.warning(
            "require_auth: Unauthorized access attempt. Expected token prefix: %s..., Got: %s",
            _SHARED_SECRET[:6] if _SHARED_SECRET else "None",
            token if token else "None"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


