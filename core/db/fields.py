# apps/core/db/fields.py
"""
Custom database fields for fiscal compliance.
"""
from decimal import Decimal, ROUND_HALF_UP
from django.db import models
from django.core.exceptions import ValidationError

from core.decimal.decimal_config import fiscal_round, NPR_PRECISION


class FiscalDecimalField(models.DecimalField):
    """
    Decimal field with fiscal rounding (ROUND_HALF_UP).

    Always stores with 4 decimal places, displays with 2.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_digits', 20)
        kwargs.setdefault('decimal_places', 4)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        val = super().to_python(value)
        if isinstance(val, Decimal):
            return val.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        return val

    def get_prep_value(self, value):
        val = super().get_prep_value(value)
        if isinstance(val, Decimal):
            return str(val.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP))
        return val


class BSDateField(models.CharField):
    """
    Field for storing Bikram Sambat dates in YYYY-MM-DD format.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 10)
        kwargs.setdefault('help_text', 'Bikram Sambat date in YYYY-MM-DD format')
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop('max_length', None)
        kwargs.pop('help_text', None)
        return name, path, args, kwargs

    def validate(self, value, model_instance):
        super().validate(value, model_instance)

        if value is None:
            return

        # Validate format
        try:
            year, month, day = map(int, value.split('-'))
            if not (2000 <= year <= 2100):
                raise ValidationError('BS year must be between 2000 and 2100')
            if not (1 <= month <= 12):
                raise ValidationError('Month must be between 1 and 12')
            if not (1 <= day <= 32):
                raise ValidationError('Day must be between 1 and 32')
        except ValueError:
            raise ValidationError('Invalid BS date format. Use YYYY-MM-DD.')


class NPRCurrencyField(FiscalDecimalField):
    """
    Field for Nepali Rupee amounts.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('verbose_name', 'Amount (NPR)')
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop('verbose_name', None)
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        from django.forms import DecimalField
        defaults = {
            'min_value': Decimal('-999999999999.9999'),
            'max_value': Decimal('999999999999.9999'),
            'decimal_places': 2,
        }
        defaults.update(kwargs)
        return DecimalField(**defaults)