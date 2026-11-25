import time
import httpx


def _raise_for_apify_http_error(response: httpx.Response, actor_id: str) -> None:
    """Translate Apify HTTP failures into clear errors without leaking credentials."""
    if response.status_code < 400:
        return
    try:
        err_msg = response.json().get("error", {}).get("message") or response.text[:240]
    except Exception:
        err_msg = response.text[:240]

    if response.status_code == 401:
        raise ValueError("Apify authentication failed (401). Check your APIFY_API_TOKEN.")
    if response.status_code == 402:
        raise RuntimeError(f"Apify usage quota or credit limit reached (402) for {actor_id}: {err_msg}")
    if response.status_code == 403:
        raise RuntimeError(f"Apify access forbidden (403) for {actor_id}: {err_msg}")
    if response.status_code == 404:
        raise RuntimeError(f"Apify resource not found (404) for {actor_id}: {err_msg}")
    raise RuntimeError(f"Apify HTTP {response.status_code} for {actor_id}: {err_msg}")


def run_apify_actor_and_fetch_items(
    actor_id: str,
    payload: dict,
    token: str,
    timeout_secs: int = 240,
) -> list[dict]:
    """Start an Apify actor run, poll until completion, and return dataset items.

    Using async run + status polling avoids 90-120s HTTP socket ReadTimeouts on
    slower search runs, and passing the token via Authorization header ensures
    credentials never appear in exception URLs.
    """
    cleaned_token = token.strip()
    if not cleaned_token:
        raise ValueError(f"APIFY_API_TOKEN is required to run {actor_id}.")

    headers = {"Authorization": f"Bearer {cleaned_token}"}
    base_url = "https://api.apify.com/v2"

    with httpx.Client(headers=headers, timeout=45.0) as client:
        initial_wait = min(60, max(5, int(timeout_secs)))
        start_resp = client.post(
            f"{base_url}/acts/{actor_id}/runs",
            params={"waitForFinish": initial_wait},
            json=payload,
            timeout=initial_wait + 15.0,
        )
        _raise_for_apify_http_error(start_resp, actor_id)
        run_data = start_resp.json()["data"]
        run_id = run_data["id"]

        deadline = time.monotonic() + timeout_secs
        while True:
            status = run_data.get("status", "")
            if status == "SUCCEEDED":
                break
            if status in {"FAILED", "ABORTED", "TIMED-OUT", "TIMED_OUT"}:
                detail = run_data.get("statusMessage") or "No details provided."
                raise RuntimeError(f"Apify actor {actor_id} ended with status {status}: {detail}")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Apify actor {actor_id} (run {run_id}) did not complete within {timeout_secs}s."
                )

            wait_secs = min(20, max(2, int(remaining)))
            poll_resp = client.get(
                f"{base_url}/actor-runs/{run_id}",
                params={"waitForFinish": wait_secs},
                timeout=wait_secs + 15.0,
            )
            _raise_for_apify_http_error(poll_resp, actor_id)
            run_data = poll_resp.json()["data"]

        dataset_id = run_data.get("defaultDatasetId")
        if not dataset_id:
            return []

        items_resp = client.get(
            f"{base_url}/datasets/{dataset_id}/items",
            params={"format": "json", "clean": "true"},
            timeout=60.0,
        )
        _raise_for_apify_http_error(items_resp, actor_id)
        data = items_resp.json()
        return data if isinstance(data, list) else []
