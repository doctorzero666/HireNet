import os
import tempfile

import pytest

from app.app import create_app


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    flask_app = create_app(config={"TESTING": True, "DATABASE_PATH": db_path})
    with flask_app.test_client() as c:
        yield c
    os.unlink(db_path)
