# apps/core/db/locks.py
"""
PostgreSQL advisory locks for concurrency control.
"""
import hashlib
import threading
from contextlib import contextmanager
from django.db import connection, transaction, DatabaseError

_lock = threading.Lock()
_active_locks = set()


@contextmanager
def advisory_lock(tenant_id: int, resource_type: str, resource_id: int,
                  timeout: int = 30, blocking: bool = True):
    """
    Acquire PostgreSQL advisory lock.

    Lock ID is 64-bit: high 32 bits = tenant_id, low 32 bits = resource hash

    Args:
        tenant_id: Tenant ID
        resource_type: Type of resource (e.g., 'inventory', 'account')
        resource_id: Resource ID
        timeout: Lock timeout in seconds (0 = no timeout)
        blocking: Whether to wait for lock or fail immediately

    Yields:
        None when lock is acquired
    """
    resource_str = f"{resource_type}:{resource_id}"
    resource_hash = int(hashlib.md5(resource_str.encode()).hexdigest()[:8], 16)
    lock_id = (tenant_id << 32) | resource_hash

    lock_key = f"{tenant_id}:{resource_type}:{resource_id}"

    with _lock:
        if lock_key in _active_locks:
            raise RuntimeError(f"Nested advisory lock detected: {lock_key}")
        _active_locks.add(lock_key)

    acquired = False
    try:
        with connection.cursor() as cursor:
            if not blocking:
                # Try to acquire without waiting
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
                acquired = cursor.fetchone()[0]
                if not acquired:
                    raise DatabaseError(f"Could not acquire advisory lock for {resource_type}:{resource_id}")
            else:
                # Blocking acquire with optional timeout
                if timeout > 0:
                    cursor.execute("SET LOCAL lock_timeout = %s", [f"{timeout}s"])
                cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
                acquired = True

            yield

    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])

        with _lock:
            _active_locks.discard(lock_key)


@contextmanager
def serializable_transaction():
    """
    Execute transaction with SERIALIZABLE isolation level.

    Use ONLY for critical financial operations where absolute consistency
    is required (e.g., posting transactions, year-end closing).

    WARNING: Higher contention, use sparingly.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SET TRANSACTION READ WRITE")
        yield


@contextmanager
def read_committed_transaction():
    """
    Execute transaction with READ COMMITTED isolation (default).
    Suitable for most operations.
    """
    with transaction.atomic():
        yield


def is_lock_active(tenant_id: int, resource_type: str, resource_id: int) -> bool:
    """Check if advisory lock is currently held (debugging only)."""
    lock_key = f"{tenant_id}:{resource_type}:{resource_id}"
    return lock_key in _active_locks