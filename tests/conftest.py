import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'files'))

import pytest
from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c
