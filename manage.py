#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

def main():
    from environ import environ

    base_dir = Path(__file__).resolve().parent.parent.parent
    environ.Env.read_env(os.path.join(base_dir, '.env'), overwrite=True)
    env = environ.Env()
    """Run administrative tasks."""
    if env.bool('DEBUG', True):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
    else:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
