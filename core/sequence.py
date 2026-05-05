# apps/core/sequence.py
"""
Sequence number generation for documents.
Thread-safe with database-backed persistence.
"""
import threading
import time
from datetime import datetime
from django.db import connection, transaction

_lock = threading.Lock()
_local_counters = {}


def next_sequence(prefix: str, tenant_id: int, year: int = None) -> str:
    """
    Generate next sequence number for a tenant.

    Format: {PREFIX}-{YEAR}-{SEQUENCE:05d}
    Example: INV-2024-00001

    Args:
        prefix: Document prefix (e.g., 'INV', 'JV', 'PAY')
        tenant_id: Tenant ID
        year: Year (default: current year)

    Returns:
        Sequence string
    """
    if year is None:
        year = datetime.now().year

    key = f"{prefix}_{tenant_id}_{year}"

    with _lock:
        if key not in _local_counters:
            # Get max from database
            with connection.cursor() as cursor:
                # Check multiple tables for the prefix
                tables = [
                    ('invoicing_invoice', 'invoice_number'),
                    ('accounts_transaction', 'reference_number'),
                    ('payments_payment', 'payment_number'),
                    ('purchases_purchase', 'purchase_number'),
                ]

                max_num = 0
                for table, column in tables:
                    try:
                        cursor.execute(f"""
                            SELECT MAX(CAST(
                                SUBSTRING({column} FROM '([0-9]+)$') AS INTEGER
                            ))
                            FROM {table}
                            WHERE tenant_id = %s AND {column} LIKE %s
                        """, [tenant_id, f"{prefix}-{year}-%"])
                        result = cursor.fetchone()[0]
                        if result and result > max_num:
                            max_num = result
                    except Exception:
                        continue

                _local_counters[key] = max_num + 1

        sequence = _local_counters[key]
        _local_counters[key] += 1

        return f"{prefix}-{year}-{str(sequence).zfill(5)}"


def generate_number(prefix: str, id: int, year: int = None) -> str:
    """
    Generate number based on ID (for import/migration).

    Args:
        prefix: Document prefix
        id: Record ID
        year: Year (default: current)

    Returns:
        Generated number
    """
    if year is None:
        year = datetime.now().year

    return f"{prefix}-{year}-{str(id).zfill(5)}"


def reset_counter(prefix: str, tenant_id: int, year: int = None):
    """
    Reset counter for testing purposes.
    """
    if year is None:
        year = datetime.now().year

    key = f"{prefix}_{tenant_id}_{year}"
    with _lock:
        _local_counters.pop(key, None)


def get_current_counter(prefix: str, tenant_id: int, year: int = None) -> int:
    """Get current counter value (for debugging)."""
    if year is None:
        year = datetime.now().year

    key = f"{prefix}_{tenant_id}_{year}"
    return _local_counters.get(key, 0)