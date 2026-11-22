from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_environment():
    assert 1 == 1


def test_hello_world():
    response = client.get('/hello_world')
    assert response.status_code == 200
    assert response.json() == {'hello': 'world'}


def test_echo():
    response = client.post('/echo', json={'text': 'test'})
    assert response.status_code == 200
    assert response.json() == {'text': 'test'}
