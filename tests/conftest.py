import os
import tempfile

import pytest

from app.app import create_app
from app.services.mock_settlement import MockSettlementProvider


@pytest.fixture
def client():
    # Inject MockSettlementProvider explicitly so the test suite stays
    # hermetic regardless of `.env` (HIRENET_SETTLEMENT_PROVIDER may now
    # default to `anvil`, which would otherwise try to dial localhost:8545
    # during create_app and crash hundreds of tests on CI / dev machines
    # without Anvil running). Tests that need a different provider build
    # their own client and pass config={"SETTLEMENT_PROVIDER": <other>}.
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    flask_app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "SETTLEMENT_PROVIDER": MockSettlementProvider(),
    })
    with flask_app.test_client() as c:
        yield c
    os.unlink(db_path)
