"""
services/ingestion/app/webhooks.py
OneDrive webhook endpoint — stub implementation.
Real implementation: download file from OneDrive share URL, then call ingest pipeline.

OneDrive sends a POST with a JSON payload like:
{
  "value": [
    {
      "subscriptionId": "...",
      "clientState": "...",
      "changeType": "created",
      "resource": "drives/{driveId}/items/{itemId}",
      "resourceData": {
        "id": "{itemId}",
        "name": "document.pdf",
        "size": 12345,
        "@odata.type": "#microsoft.graph.driveItem"
      }
    }
  ]
}
"""
import logging
from fastapi import APIRouter, Request

logger = logging.getLogger("ingestion.webhooks")
router = APIRouter()


@router.post("/webhooks/onedrive")
async def onedrive_webhook(request: Request):
    """
    Receive OneDrive change notifications.
    Phase 2: stub — logs payload, returns 200 (required by OneDrive validation).
    Phase 3+: download the file and call the ingest pipeline.
    """
    # OneDrive sends a GET with validationToken during subscription setup
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        logger.info(f"OneDrive webhook validation request received")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=validation_token, status_code=200)

    payload = await request.json()
    logger.info(f"OneDrive webhook received: {payload}")

    # TODO Phase 3+: for each item in payload["value"]:
    #   1. Extract driveId and itemId from item["resource"]
    #   2. Download file bytes via Graph API
    #   3. Call ingest pipeline with source_channel="onedrive"

    return {"status": "received", "message": "Webhook stub — not yet processing files"}
