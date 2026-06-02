import pytest
from app.app import create_app


@pytest.fixture
def client():
    flask_app = create_app()
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c
