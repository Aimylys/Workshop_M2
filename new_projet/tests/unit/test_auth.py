from fastapi.testclient import TestClient


def test_password_hash_and_verify(auth):
    from app import passwords  # noqa: PLC0415 - paquet chargé par la fixture

    h = passwords.hash_password("correct horse battery")
    assert passwords.verify(h, "correct horse battery")
    assert not passwords.verify(h, "mauvais")
    assert not passwords.verify("pas-un-hash", "x")


def test_login_input_validated(auth):
    client = TestClient(auth.app)
    assert client.post("/login", json={"username": "", "password": "x"}).status_code == 422
    assert client.post("/login", json={"username": "a" * 65, "password": "x"}).status_code == 422
