import pytest
from unittest.mock import MagicMock, patch


@patch("db.get_client")
def test_create_run_returns_id(mock_get_client):
    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "abc-123", "platform": "ubereats", "status": "running"}
    ]
    mock_get_client.return_value = mock_client

    import db
    run_id = db.create_run("ubereats")
    assert run_id == "abc-123"


@patch("db.get_client")
def test_finish_run_updates_status(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    import db
    db.finish_run("abc-123", "success", records_saved=42)

    update_call = mock_client.table.return_value.update.call_args[0][0]
    assert update_call["status"] == "success"
    assert update_call["records_saved"] == 42
