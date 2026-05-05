# apps/core/decimal_config.py
"""
Fiscal decimal configuration for Nepali tax compliance.
CRITICAL: Must use ROUND_HALF_UP, not ROUND_HALF_EVEN (banker's rounding).
"""
from decimal import Decimal, ROUND_HALF_UP, getcontext, InvalidOperation

# Set global context
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_UP

# Constants
NPR_PRECISION = 4  # Storage precision
NPR_DISPLAY_PRECISION = 2  # Display precision
VAT_STANDARD_RATE = Decimal('13.00')
VAT_ZERO_RATE = Decimal('0.00')


def fiscal_round(value: Decimal, places: int = NPR_DISPLAY_PRECISION) -> Decimal:
    """
    Round decimal using ROUND_HALF_UP (fiscal rounding).

    Args:
        value: Decimal value to round
        places: Number of decimal places

    Returns:
        Rounded Decimal

    Example:
        >>> fiscal_round(Decimal('99.995'))
        Decimal('100.00')
        >>> fiscal_round(Decimal('99.994'))
        Decimal('99.99')
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))

    quantize_str = '0.' + '0' * places
    return value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


def safe_decimal(value, fallback: str = '0') -> Decimal:
    """
    Safely convert value to Decimal.

    Args:
        value: Value to convert
        fallback: Fallback value if conversion fails

    Returns:
        Decimal value
    """
    if value is None:
        return Decimal(fallback)

    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(fallback)


def calc_vat(amount: Decimal, rate: Decimal = VAT_STANDARD_RATE) -> Decimal:
    """
    Calculate VAT amount using fiscal rounding.

    Args:
        amount: Taxable amount
        rate: VAT rate percentage

    Returns:
        VAT amount rounded to 2 decimal places

    Example:
        >>> calc_vat(Decimal('1000.00'))
        Decimal('130.00')
    """
    amount = safe_decimal(amount)
    rate = safe_decimal(rate)
    vat = amount * (rate / 100)
    return fiscal_round(vat, NPR_DISPLAY_PRECISION)


def calc_line_total(
        quantity: Decimal,
        unit_price: Decimal,
        discount_percent: Decimal = Decimal('0'),
        vat_rate: Decimal = VAT_STANDARD_RATE,
        is_vat_applicable: bool = False
) -> dict:
    """
    Calculate line item totals with proper fiscal rounding.

    Returns dict with:
        - line_total: Total including VAT
        - discount_amount: Discount amount
        - vat_amount: VAT amount
        - taxable_amount: Amount after discount, before VAT
        - gross_amount: Quantity * unit_price (before discount)
    """
    qty = safe_decimal(quantity)
    price = safe_decimal(unit_price)
    disc_pct = safe_decimal(discount_percent)
    vat_rate = safe_decimal(vat_rate)

    # Calculate gross
    gross = qty * price

    # Calculate discount
    discount_amount = fiscal_round(gross * (disc_pct / 100), NPR_PRECISION)
    taxable_amount = gross - discount_amount

    # Calculate VAT
    vat_amount = Decimal('0')
    if is_vat_applicable:
        vat_amount = fiscal_round(taxable_amount * (vat_rate / 100), NPR_PRECISION)

    # Line total
    line_total = taxable_amount + vat_amount

    return {
        'line_total': str(fiscal_round(line_total, NPR_PRECISION)),
        'discount_amount': str(discount_amount),
        'vat_amount': str(vat_amount),
        'taxable_amount': str(fiscal_round(taxable_amount, NPR_PRECISION)),
        'gross_amount': str(fiscal_round(gross, NPR_PRECISION)),
    }


def sum_lines(lines: list) -> dict:
    """
    Sum multiple line items.

    Args:
        lines: List of dicts with line_total, vat_amount, discount_amount

    Returns:
        Dict with subtotal, discount_amount, taxable_amount, vat_amount, total_amount
    """
    subtotal = Decimal('0')
    discount_amount = Decimal('0')
    vat_amount = Decimal('0')

    for line in lines:
        line_total = safe_decimal(line.get('line_total', '0'))
        vat_amt = safe_decimal(line.get('vat_amount', '0'))
        disc_amt = safe_decimal(line.get('discount_amount', '0'))

        # Reverse calculate: line_total = taxable + vat, so taxable = line_total - vat
        taxable = line_total - vat_amt

        subtotal += taxable + disc_amt  # Add back discount to get gross
        discount_amount += disc_amt
        vat_amount += vat_amt

    taxable_amount = subtotal - discount_amount
    total_amount = taxable_amount + vat_amount

    return {
        'subtotal': str(fiscal_round(subtotal, NPR_PRECISION)),
        'discount_amount': str(fiscal_round(discount_amount, NPR_PRECISION)),
        'taxable_amount': str(fiscal_round(taxable_amount, NPR_PRECISION)),
        'vat_amount': str(fiscal_round(vat_amount, NPR_PRECISION)),
        'total_amount': str(fiscal_round(total_amount, NPR_PRECISION)),
    }


def validate_double_entry(debits: Decimal, credits: Decimal) -> bool:
    """
    Validate that debits equal credits in double-entry accounting.

    Args:
        debits: Total debits
        credits: Total credits

    Returns:
        True if balanced, False otherwise
    """
    debits = safe_decimal(debits)
    credits = safe_decimal(credits)
    return fiscal_round(debits) == fiscal_round(credits)