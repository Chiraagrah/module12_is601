from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.calculation import (
    Addition,
    Calculation,
    Division,
    Multiplication,
    Subtraction,
)
from app.models.user import User
from app.schemas.calculation import CalculationBase, CalculationType, CalculationUpdate
from app.schemas.user import PasswordUpdate, UserCreate


@pytest.mark.parametrize(
    "calculation_class",
    [Addition, Subtraction, Multiplication, Division],
)
@pytest.mark.parametrize("inputs", ["not-a-list", [1]])
def test_calculation_operations_reject_invalid_inputs(calculation_class, inputs):
    calculation = calculation_class(user_id=uuid4(), inputs=inputs)
    with pytest.raises(ValueError):
        calculation.get_result()


def test_base_calculation_result_and_representation():
    calculation = Calculation(user_id=uuid4(), inputs=[1, 2], type="calculation")
    with pytest.raises(NotImplementedError):
        calculation.get_result()
    assert repr(calculation) == "<Calculation(type=calculation, inputs=[1, 2])>"


def test_user_constructor_alias_and_update():
    user = User(
        first_name="Before",
        last_name="Name",
        email="before@example.com",
        username="before",
        hashed_password="stored-hash",
    )
    assert user.password == user.hashed_password == "stored-hash"

    updated = user.update(first_name="After")
    assert updated is user
    assert user.first_name == "After"
    assert user.updated_at is not None


@pytest.mark.parametrize(
    ("password", "error"),
    [
        ("lowercase123!", "uppercase"),
        ("UPPERCASE123!", "lowercase"),
        ("NoDigits!!", "digit"),
        ("NoSpecial123", "special"),
    ],
)
def test_user_create_rejects_weak_passwords(password, error):
    with pytest.raises(ValidationError, match=error):
        UserCreate(
            first_name="Test",
            last_name="User",
            email="test@example.com",
            username="testuser",
            password=password,
            confirm_password=password,
        )


def test_user_create_rejects_password_mismatch_and_short_password():
    base = {
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "username": "testuser",
    }
    with pytest.raises(ValidationError, match="Passwords do not match"):
        UserCreate(
            **base,
            password="SecurePass123!",
            confirm_password="DifferentPass123!",
        )

    short_password = UserCreate.model_construct(
        **base,
        password="Short1!",
        confirm_password="Short1!",
    )
    with pytest.raises(ValueError, match="at least 8 characters"):
        short_password.validate_password_strength()


@pytest.mark.parametrize(
    ("new_password", "confirmation", "error"),
    [
        ("NewPass123!", "OtherPass123!", "do not match"),
        ("OldPass123!", "OldPass123!", "different from current"),
    ],
)
def test_password_update_rejects_invalid_password_changes(
    new_password, confirmation, error
):
    with pytest.raises(ValidationError, match=error):
        PasswordUpdate(
            current_password="OldPass123!",
            new_password=new_password,
            confirm_new_password=confirmation,
        )


def test_password_update_accepts_valid_change():
    update = PasswordUpdate(
        current_password="OldPass123!",
        new_password="NewPass123!",
        confirm_new_password="NewPass123!",
    )
    assert update.new_password == "NewPass123!"


def test_calculation_schema_rejects_invalid_validation_inputs():
    invalid_calculation = CalculationBase.model_construct(
        type=CalculationType.ADDITION, inputs=[1]
    )
    with pytest.raises(ValueError, match="At least two numbers"):
        invalid_calculation.validate_inputs()

    with pytest.raises(ValidationError, match="Cannot divide by zero"):
        CalculationBase(type="division", inputs=[10, 0])

    invalid_update = CalculationUpdate.model_construct(inputs=[1])
    with pytest.raises(ValueError, match="At least two numbers"):
        invalid_update.validate_inputs()
