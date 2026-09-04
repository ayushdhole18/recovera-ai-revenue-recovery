from decimal import Decimal
from typing import Union, Optional

# Fixed exchange rate for demo consistency (1 USD = 83.50 INR)
EXCHANGE_RATE_USD_TO_INR = Decimal("83.50")


def convert_usd_to_inr(amount: Union[float, Decimal, int, str, None]) -> Decimal:
    """
    Converts USD amount stored in the database to INR using the fixed exchange rate.
    Does NOT mutate the underlying database value.
    """
    if amount is None:
        return Decimal("0.00")
    return (Decimal(str(amount)) * EXCHANGE_RATE_USD_TO_INR).quantize(Decimal("0.01"))


def format_inr(amount: Union[float, Decimal, int, str, None], is_converted: bool = False) -> str:
    """
    Centralized currency formatting utility for all frontend monetary displays.
    Always returns formatted string with ₹ (INR) symbol.

    :param amount: The numerical or Decimal monetary amount.
    :param is_converted: If True, amount is already in INR. If False, converts USD DB amount to INR first.
    :return: Formatted currency string, e.g. "₹4,174.17"
    """
    if amount is None:
        return "₹0.00"
    dec_val = Decimal(str(amount))
    if not is_converted:
        dec_val = convert_usd_to_inr(dec_val)
    else:
        dec_val = dec_val.quantize(Decimal("0.01"))
    return f"₹{dec_val:,.2f}"
