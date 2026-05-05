# config/wsgi.py
import os
from pathlib import Path
import environ

# Load env vars before Django imports
env = environ.Env()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
environ.Env.read_env(os.path.join(BASE_DIR, '.env'), overwrite=True)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()