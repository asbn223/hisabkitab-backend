# apps/core/exceptions.py
"""
Custom exceptions and error handling.
"""
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError


class LedgerSyncError(Exception):
    """Base exception for LedgerSync."""
    pass


class InsufficientStockError(LedgerSyncError):
    """Raised when stock is insufficient."""
    pass


class DoubleEntryError(LedgerSyncError):
    """Raised when debits don't equal credits."""
    pass


class ImmutableEntityError(LedgerSyncError):
    """Raised when trying to modify immutable entity."""
    pass


class TenantRequiredError(LedgerSyncError):
    """Raised when tenant is required but not provided."""
    pass


class FiscalYearClosedError(LedgerSyncError):
    """Raised when fiscal year is closed."""
    pass


class PaymentGatewayError(LedgerSyncError):
    """Raised when payment gateway returns error."""
    pass


def custom_exception_handler(exc, context):
    """
    Custom exception handler for DRF.
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    # If exception is already handled, return response
    if response is not None:
        return response

    # Handle Django exceptions
    if isinstance(exc, ValidationError):
        return Response(
            {'errors': exc.message_dict if hasattr(exc, 'message_dict') else {'non_field_errors': exc.messages}},
            status=status.HTTP_400_BAD_REQUEST
        )

    if isinstance(exc, PermissionDenied):
        return Response(
            {'errors': {'detail': str(exc)}},
            status=status.HTTP_403_FORBIDDEN
        )

    if isinstance(exc, IntegrityError):
        return Response(
            {'errors': {'detail': 'Database integrity error. Possible duplicate entry.'}},
            status=status.HTTP_409_CONFLICT
        )

    # Handle custom exceptions
    if isinstance(exc, InsufficientStockError):
        return Response(
            {'errors': {'stock': str(exc)}},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    if isinstance(exc, DoubleEntryError):
        return Response(
            {'errors': {'accounting': str(exc)}},
            status=status.HTTP_400_BAD_REQUEST
        )

    if isinstance(exc, ImmutableEntityError):
        return Response(
            {'errors': {'immutable': str(exc)}},
            status=status.HTTP_409_CONFLICT
        )

    if isinstance(exc, TenantRequiredError):
        return Response(
            {'errors': {'tenant': str(exc)}},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Log unhandled exceptions
    import logging
    logger = logging.getLogger('ledgersync')
    logger.exception("Unhandled exception")

    # Return generic error for unhandled exceptions
    return Response(
        {'errors': {'detail': 'An unexpected error occurred.'}},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )