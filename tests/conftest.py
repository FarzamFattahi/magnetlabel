import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from magnetlabel.server import create_app


def png(color=(40, 50, 60), size=(80, 60)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "project"))


@pytest.fixture
def store(client):
    return client.app.state.store
