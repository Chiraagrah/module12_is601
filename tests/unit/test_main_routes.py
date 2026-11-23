import asyncio
import runpy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import main
from app.models.calculation import Calculation
from app.schemas.calculation import CalculationUpdate
from app.schemas.user import UserCreate, UserLogin


def _run(coroutine):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def _db(first=None, all_items=None):
    db = MagicMock()
    query = db.query.return_value
    filtered = query.filter.return_value
    filtered.first.return_value = first
    filtered.all.return_value = all_items or []
    return db


def test_lifespan_creates_tables(monkeypatch):
    create_all = MagicMock()
    monkeypatch.setattr(main.Base.metadata, "create_all", create_all)

    async def exercise_lifespan():
        async with main.lifespan(main.app):
            pass

    _run(exercise_lifespan())
    create_all.assert_called_once_with(bind=main.engine)


def test_health_and_calculator_routes():
    assert main.read_health() == {"status": "ok"}
    assert isinstance(main.calculator_page(), main.FileResponse)

    values = main.CalculatorInput(a=12, b=3)
    assert main.calculate_add(values) == {"result": 15}
    assert main.calculate_subtract(values) == {"result": 9}
    assert main.calculate_multiply(values) == {"result": 36}
    assert main.calculate_divide(values) == {"result": 4}

    with patch.object(main, "divide", side_effect=ValueError("divide error")):
        response = main.calculate_divide(values)
    assert response.status_code == 400
    assert response.body == b'{"error":"divide error"}'


def test_register_success_and_validation_error():
    registration = UserCreate(
        first_name="Test",
        last_name="User",
        email="register@example.com",
        username="registeruser",
        password="SecurePass123!",
        confirm_password="SecurePass123!",
    )
    db = MagicMock()
    user = object()
    with patch.object(main.User, "register", return_value=user) as register_user:
        assert main.register(registration, db) is user
    register_user.assert_called_once()
    assert "confirm_password" not in register_user.call_args.args[1]
    db.commit.assert_called_once_with()
    db.refresh.assert_called_once_with(user)

    with patch.object(main.User, "register", side_effect=ValueError("duplicate")):
        with pytest.raises(HTTPException) as exc_info:
            main.register(registration, db)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "duplicate"
    db.rollback.assert_called_once_with()


def test_json_login_rejects_bad_credentials():
    with patch.object(main.User, "authenticate", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            main.login_json(UserLogin(username="testuser", password="SecurePass123!"), MagicMock())
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid username or password"


def test_json_login_success_payload():
    user = SimpleNamespace(
        id=uuid4(),
        username="testuser",
        email="test@example.com",
        first_name="Test",
        last_name="User",
        is_active=True,
        is_verified=False,
    )
    auth_result = {
        "access_token": "access",
        "refresh_token": "refresh",
        "user": user,
        "expires_at": datetime(2025, 1, 1),
    }
    db = MagicMock()
    with patch.object(main.User, "authenticate", return_value=auth_result):
        response = main.login_json(
            UserLogin(username="testuser", password="SecurePass123!"), db
        )
    assert response.access_token == "access"
    assert response.expires_at.tzinfo == timezone.utc
    db.commit.assert_called_once_with()

    auth_result["expires_at"] = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with patch.object(main.User, "authenticate", return_value=auth_result):
        response = main.login_json(
            UserLogin(username="testuser", password="SecurePass123!"), MagicMock()
        )
    assert response.expires_at > datetime.now(timezone.utc)


def test_form_login_failure_and_success():
    form_data = SimpleNamespace(username="testuser", password="SecurePass123!")
    with patch.object(main.User, "authenticate", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            main.login_form(form_data, MagicMock())
    assert exc_info.value.status_code == 401

    auth_result = {"access_token": "token"}
    with patch.object(main.User, "authenticate", return_value=auth_result):
        assert main.login_form(form_data, MagicMock()) == {
            "access_token": "token",
            "token_type": "bearer",
        }


def test_create_calculation_success_and_bad_operation():
    current_user = SimpleNamespace(id=uuid4())
    calculation_data = main.CalculationBase(type="addition", inputs=[2, 3])
    calculation = SimpleNamespace(get_result=MagicMock(return_value=5), result=None)
    db = MagicMock()
    with patch.object(Calculation, "create", return_value=calculation):
        assert main.create_calculation(calculation_data, current_user, db) is calculation
    assert calculation.result == 5
    db.add.assert_called_once_with(calculation)
    db.commit.assert_called_once_with()
    db.refresh.assert_called_once_with(calculation)

    with patch.object(Calculation, "create", side_effect=ValueError("invalid operation")):
        with pytest.raises(HTTPException) as exc_info:
            main.create_calculation(calculation_data, current_user, db)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid operation"
    db.rollback.assert_called_once_with()


def test_list_calculations_returns_users_results():
    calculations = [object(), object()]
    db = _db(all_items=calculations)
    result = main.list_calculations(SimpleNamespace(id=uuid4()), db)
    assert result == calculations
    db.query.assert_called_once_with(Calculation)


def test_get_calculation_invalid_missing_and_found():
    current_user = SimpleNamespace(id=uuid4())
    with pytest.raises(HTTPException) as exc_info:
        main.get_calculation("not-a-uuid", current_user, _db())
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        main.get_calculation(str(uuid4()), current_user, _db())
    assert exc_info.value.status_code == 404

    calculation = object()
    assert main.get_calculation(str(uuid4()), current_user, _db(first=calculation)) is calculation


def test_update_calculation_invalid_missing_and_found():
    current_user = SimpleNamespace(id=uuid4())
    update = CalculationUpdate()
    with pytest.raises(HTTPException) as exc_info:
        main.update_calculation("bad-id", update, current_user, _db())
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        main.update_calculation(str(uuid4()), update, current_user, _db())
    assert exc_info.value.status_code == 404

    calculation = SimpleNamespace(inputs=[2, 3], result=5, get_result=lambda: 42)
    db = _db(first=calculation)
    result = main.update_calculation(str(uuid4()), update, current_user, db)
    assert result is calculation
    assert calculation.result == 5
    assert calculation.updated_at is not None
    db.commit.assert_called_once_with()
    db.refresh.assert_called_once_with(calculation)

    update_inputs = CalculationUpdate(inputs=[6, 7])
    main.update_calculation(str(uuid4()), update_inputs, current_user, db)
    assert calculation.inputs == [6, 7]
    assert calculation.result == 42


def test_delete_calculation_invalid_missing_and_found():
    current_user = SimpleNamespace(id=uuid4())
    with pytest.raises(HTTPException) as exc_info:
        main.delete_calculation("bad-id", current_user, _db())
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        main.delete_calculation(str(uuid4()), current_user, _db())
    assert exc_info.value.status_code == 404

    calculation = object()
    db = _db(first=calculation)
    assert main.delete_calculation(str(uuid4()), current_user, db) is None
    db.delete.assert_called_once_with(calculation)
    db.commit.assert_called_once_with()


def test_server_entry_point_runs_uvicorn():
    script = Path(main.__file__)
    with patch("uvicorn.run") as run_server:
        runpy.run_path(str(script), run_name="__main__")
    run_server.assert_called_once_with(
        "app.main:app", host="127.0.0.1", port=8001, log_level="info"
    )
