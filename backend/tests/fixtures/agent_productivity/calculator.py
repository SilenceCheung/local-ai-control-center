"""Small production-agent fixture with two intentional defects."""


def add(left: float, right: float) -> float:
    return left + right


def multiply(left: float, right: float) -> float:
    raise NotImplementedError("implement multiply")


def divide(left: float, right: float) -> float:
    return left / right
