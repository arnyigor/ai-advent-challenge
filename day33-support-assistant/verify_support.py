"""Wait for application readiness after an operator-triggered restart."""
import asyncio
import httpx


async def wait_ready(client):
    for _ in range(20):
        try:
            response = await client.get('/healthz')
            if response.status_code == 200:
                (await client.get('/')).raise_for_status()
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    raise RuntimeError('Application did not become ready within 20 seconds')
