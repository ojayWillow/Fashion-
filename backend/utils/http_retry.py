"""Shared HTTP retry logic for all store fetchers and stock checkers."""
import time
import logging
import requests

logger = logging.getLogger("http_retry")


def request_with_retry(
    url: str,
    method: str = "GET",
    max_retries: int = 3,
    timeout: int = 15,
    session: requests.Session | None = None,
    **kwargs,
) -> requests.Response:
    """Make an HTTP request with retry on 429 rate limits.

    Works for any store. Raises on final failure.
    """
    client = session or requests
    for attempt in range(max_retries):
        try:
            resp = client.request(method, url, timeout=timeout, **kwargs)
            if resp.status_code == 429:
                wait = (attempt + 1) * 3
                logger.warning(f"Rate limited on {url}, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            return resp
        except requests.ConnectionError as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 2
                logger.warning(f"Connection error on {url}, retrying in {wait}s: {e}")
                time.sleep(wait)
                continue
            raise
        except requests.Timeout as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 2
                logger.warning(f"Timeout on {url}, retrying in {wait}s: {e}")
                time.sleep(wait)
                continue
            raise
    # Final attempt — let it raise naturally
    resp = client.request(method, url, timeout=timeout, **kwargs)
    return resp
