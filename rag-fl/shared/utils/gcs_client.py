"""
shared/utils/gcs_client.py
GCS operations — works identically with fake-gcs-server (local) and real GCS (production).
Switch is purely via GCS_ENDPOINT env var. Zero conditional logic in callers.
"""
import os
from google.cloud import storage
from google.auth.credentials import AnonymousCredentials


def get_gcs_client() -> storage.Client:
    """Return a GCS client configured for local or production."""
    endpoint = os.getenv("GCS_ENDPOINT", "https://storage.googleapis.com")
    if "fake-gcs" in endpoint or "4443" in endpoint:
        return storage.Client(
            credentials=AnonymousCredentials(),
            project="local-project",
            client_options={"api_endpoint": endpoint},
        )
    return storage.Client()


def upload_bytes(
    file_bytes: bytes,
    gcs_path: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload bytes to GCS. Returns the full gs:// URI."""
    bucket_name = os.getenv("GCS_BUCKET", "rag-fl-documents")
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)
    blob.upload_from_string(file_bytes, content_type=content_type)
    return f"gs://{bucket_name}/{gcs_path}"


def download_bytes(gcs_path: str) -> bytes:
    """Download a GCS object and return raw bytes."""
    bucket_name = os.getenv("GCS_BUCKET", "rag-fl-documents")
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)
    return blob.download_as_bytes()


def blob_exists(gcs_path: str) -> bool:
    bucket_name = os.getenv("GCS_BUCKET", "rag-fl-documents")
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    return bucket.blob(gcs_path).exists()
