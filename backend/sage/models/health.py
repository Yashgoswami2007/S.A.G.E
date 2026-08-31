import httpx

async def check_model_health(base_url: str) -> bool:
    """
    Checks if a model server at base_url is alive by querying /v1/models or pinging port.
    """
    url = f"{base_url.rstrip('/')}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except Exception:
        return False
