import pytest

from aroiod.__main__ import create
from aroiod.web import build_app


@pytest.fixture
def device(tmp_path):
    d = create(tmp_path / "data", sim=True, model="AroioLT", board="pi4", fast=True)
    return d


@pytest.fixture
async def client(aiohttp_client, device):
    app = build_app(device)

    async def on_start(_app):
        device.start()
        device.wizard.publish()

    app.on_startup.append(on_start)
    return await aiohttp_client(app)
