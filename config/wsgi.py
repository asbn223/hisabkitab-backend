import os
from pathlib import Path
import environ

# Load .env if it exists (local dev), otherwise OS env vars (Render) are already available
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_file = os.path.join(BASE_DIR, '.env')
if os.path.exists(env_file):
    environ.Env.read_env(env_file, overwrite=True)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()