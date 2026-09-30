import asyncio

import httpx
import pytest

from backend.providers.itunes import ITunesProvider, ProviderUnavailable


def test_provider_maps_network_failure_to_user_safe_error():
    async def run():
        provider = ITunesProvider()

        def offline(request):
            raise httpx.ConnectError("socket unavailable", request=request)

        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(offline), timeout=1)
        with pytest.raises(ProviderUnavailable, match="could not be reached"):
            await provider.search("a query")
        await provider.close()

    asyncio.run(run())
