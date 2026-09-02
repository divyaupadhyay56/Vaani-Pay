from __future__ import annotations

import logging

logger = logging.getLogger("vaani_pay")


def safe_error_message(e: Exception) -> str:
    
    logger.exception("Unhandled error")
    return "Something went wrong while processing your request. Please try again."