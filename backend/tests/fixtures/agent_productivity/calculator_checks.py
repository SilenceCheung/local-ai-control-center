import pytest

from calculator import add, divide, multiply


def test_add() -> None:
    assert add(2, 3) == 5


def test_multiply() -> None:
    assert multiply(6, 7) == 42
    assert multiply(-2, 4) == -8


def test_divide() -> None:
    assert divide(9, 3) == 3


def test_divide_by_zero_has_domain_error() -> None:
    with pytest.raises(ValueError, match="right must not be zero"):
        divide(1, 0)
