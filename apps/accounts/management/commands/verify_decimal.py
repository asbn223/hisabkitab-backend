# apps/core/management/commands/verify_decimal.py
"""
Verify fiscal rounding compliance.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand

from apps.core.decimal_config import fiscal_round, calc_vat, calc_line_total


class Command(BaseCommand):
    help = 'Verify fiscal rounding compliance for tax calculations'

    def handle(self, *args, **options):
        self.stdout.write("Testing fiscal rounding (ROUND_HALF_UP)...")

        test_cases = [
            # (input, expected, description)
            (Decimal('99.995'), Decimal('100.00'), 'Half-up rounding up'),
            (Decimal('99.994'), Decimal('99.99'), 'Half-up rounding down'),
            (Decimal('99.996'), Decimal('100.00'), 'Above half rounds up'),
            (Decimal('99.991'), Decimal('99.99'), 'Below half rounds down'),
        ]

        all_passed = True

        for value, expected, desc in test_cases:
            result = fiscal_round(value)
            passed = result == expected
            status = '✓' if passed else '✗'
            self.stdout.write(
                f"  {status} {desc}: {value} -> {result} (expected {expected})"
            )
            if not passed:
                all_passed = False

        # Test VAT calculation
        self.stdout.write("\nTesting VAT calculation...")
        vat_tests = [
            (Decimal('1000.00'), Decimal('13.00'), Decimal('130.00')),
            (Decimal('99.99'), Decimal('13.00'), Decimal('13.00')),
            (Decimal('100.00'), Decimal('13.00'), Decimal('13.00')),
        ]

        for amount, rate, expected_vat in vat_tests:
            vat = calc_vat(amount, rate)
            passed = vat == expected_vat
            status = '✓' if passed else '✗'
            self.stdout.write(
                f"  {status} VAT on {amount} @ {rate}% = {vat} (expected {expected_vat})"
            )
            if not passed:
                all_passed = False

        # Test line calculation
        self.stdout.write("\nTesting line item calculation...")
        line = calc_line_total(
            quantity=Decimal('10'),
            unit_price=Decimal('100.00'),
            discount_percent=Decimal('10'),
            vat_rate=Decimal('13'),
            is_vat_applicable=True
        )

        expected = {
            'line_total': '1017.0000',
            'discount_amount': '100.0000',
            'vat_amount': '117.0000',
            'taxable_amount': '900.0000',
            'gross_amount': '1000.0000',
        }

        for key, expected_val in expected.items():
            actual = line[key]
            passed = actual == expected_val
            status = '✓' if passed else '✗'
            self.stdout.write(f"  {status} {key}: {actual} (expected {expected_val})")
            if not passed:
                all_passed = False

        if all_passed:
            self.stdout.write(self.style.SUCCESS('\n✓ All tests passed - Fiscal rounding is correct'))
        else:
            self.stdout.write(self.style.ERROR('\n✗ Some tests failed - Check decimal configuration'))