import logging
import os
from dataclasses import dataclass

import boto3
import httpx
from botocore.config import Config

from shared.retry import retry_async, retry_sync

logger = logging.getLogger(__name__)


@dataclass
class UploadedMedia:
    key: str
    public_url: str
    mime_type: str
    data: bytes


def _get_r2_client():
    account_id = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _r2_public_url(key: str) -> str:
    domain = os.environ["R2_PUBLIC_DOMAIN"].rstrip("/")
    return f"{domain}/{key.lstrip('/')}"


async def download_and_upload(media_url: str, job_id: str, mime_type: str) -> UploadedMedia:
    """Download media bytes from media_url and upload to Cloudflare R2."""
    logger.info("Downloading media from %s", media_url[:80])
    
    async def download():
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(media_url)
            resp.raise_for_status()
            return resp.headers, resp.content

    headers, data = await retry_async(download, max_retries=3, initial_delay=1.0)

    detected = headers.get("content-type", "").split(";")[0].strip()
    final_mime = detected if detected and detected != "application/octet-stream" else mime_type
    logger.info("Downloaded %.2f MB mime=%s", len(data) / 1024 / 1024, final_mime)

    ext = "mp4" if final_mime.startswith("video") else "jpg"
    key = f"{job_id}.{ext}"

    logger.info("Uploading to R2 key=%s", key)
    s3 = _get_r2_client()
    
    retry_sync(
        s3.put_object,
        Bucket=os.environ["R2_BUCKET_NAME"],
        Key=key,
        Body=data,
        ContentType=final_mime,
        max_retries=3,
        initial_delay=1.0
    )

    public_url = _r2_public_url(key)
    logger.info("R2 upload complete: %s", public_url)
    return UploadedMedia(key=key, public_url=public_url, mime_type=final_mime, data=data)


def upload_bytes(data: bytes, key: str, mime_type: str) -> str:
    """Upload raw bytes to R2 and return its public URL."""
    s3 = _get_r2_client()
    retry_sync(
        s3.put_object,
        Bucket=os.environ["R2_BUCKET_NAME"],
        Key=key,
        Body=data,
        ContentType=mime_type,
        max_retries=3,
        initial_delay=1.0
    )
    return _r2_public_url(key)


def delete_from_r2(key: str) -> None:
    try:
        s3 = _get_r2_client()
        s3.delete_object(Bucket=os.environ["R2_BUCKET_NAME"], Key=key)
        logger.info("Deleted R2 object: %s", key)
    except Exception:
        logger.exception("Failed to delete R2 object %s", key)

