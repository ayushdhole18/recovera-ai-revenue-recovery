from decimal import Decimal
import pytest
from app.utils.currency import convert_usd_to_inr, format_inr, EXCHANGE_RATE_USD_TO_INR


def test_fixed_exchange_rate():
    assert EXCHANGE_RATE_USD_TO_INR == Decimal("83.50")


def test_convert_usd_to_inr():
    usd_val = Decimal("100.00")
    inr_val = convert_usd_to_inr(usd_val)
    assert inr_val == Decimal("8350.00")


def test_convert_usd_to_inr_none():
    assert convert_usd_to_inr(None) == Decimal("0.00")


def test_format_inr_unconverted():
    usd_val = Decimal("100.00")
    formatted = format_inr(usd_val, is_converted=False)
    assert formatted == "₹8,350.00"


def test_format_inr_already_converted():
    inr_val = Decimal("8350.00")
    formatted = format_inr(inr_val, is_converted=True)
    assert formatted == "₹8,350.00"


def test_format_inr_none():
    assert format_inr(None) == "₹0.00"
