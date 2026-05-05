# config/settings/base.py
import os
from pathlib import Path
from decimal import ROUND_HALF_UP
from environ import environ
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Try to load .env file if it exists (local development)
env_file = os.path.join(BASE_DIR, '.env')
if os.path.exists(env_file):
    environ.Env.read_env(env_file, overwrite=True)

# Initialize env — this will read from os.environ automatically
env = environ.Env()

# Now these will work whether from .env file or OS env vars
FIELD_ENCRYPTION_KEY = env.str('FIELD_ENCRYPTION_KEY')
SECRET_KEY = env.str('SECRET_KEY')
DEBUG = env.bool('DEBUG', default=False)

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

INSTALLED_APPS = [
"unfold",  # before django.contrib.admin
    "unfold.contrib.filters",  # optional, if special filters are needed
    "unfold.contrib.forms",  # optional, if special form elements are needed
    "unfold.contrib.inlines",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',

    # Third-party
    'rest_framework',
    'corsheaders',
    'django_filters',

    # Local apps
    'apps.tenants',
    'apps.accounts',
    'apps.inventory',
    'apps.invoicing',
    'apps.purchases',
    'apps.payments',
    'apps.tax',
    'apps.audit',
    'apps.reports',
    'apps.integrations',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.tenants.middleware.TenantMiddleware',  # Multi-tenancy
    'apps.audit.middleware.AuditLogMiddleware',  # Request auditing
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env.str('DB_NAME'),
        'USER': env.str('DB_USER'),
        'PASSWORD': env.str('DB_PASS'),
        'HOST': env.str('DB_HOST'),
        'PORT': env.str('DB_PORT'),
        'OPTIONS': {
            'options': '-c search_path=public'
        },
        'ATOMIC_REQUESTS': True,
    }
}

# Decimal Configuration - CRITICAL for fiscal compliance
DECIMAL_CONTEXT = {
    'precision': 28,
    'rounding': ROUND_HALF_UP,  # Nepali tax requirement
}

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'apps.tenants.permissions.TenantPermission',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    # 'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
}

# Timezone - Nepal
TIME_ZONE = 'Asia/Kathmandu'
USE_TZ = True
LANGUAGE_CODE = 'en-us'
USE_I18N = True
USE_L10N = True

# Static/Media
STATIC_URL = '/static/'
MEDIA_URL = '/media/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'media'

# Payment Gateway Settings
ESEWA_MERCHANT_ID = os.getenv('ESEWA_MERCHANT_ID')
ESEWA_SECRET_KEY = os.getenv('ESEWA_SECRET_KEY')
ESEWA_BASE_URL = 'https://epay.esewa.com.np/api/epay/main/v2/form'

KHALTI_SECRET_KEY = os.getenv('KHALTI_SECRET_KEY')
KHALTI_BASE_URL = 'https://khalti.com/api/v2/payment/'

# Security
# SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'False') == 'True'
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True
# SECURE_BROWSER_XSS_FILTER = True
# SECURE_CONTENT_TYPE_NOSNIFF = True
# X_FRAME_OPTIONS = 'DENY'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'nepali_accounting': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS
if DEBUG:
    CORS_ORIGIN_ALLOW_ALL = True  # If this is used then `CORS_ORIGIN_WHITELIST` will not have any effect
    CORS_ALLOW_CREDENTIALS = True
    CORS_ALLOW_HEADERS = ["*"]

SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_SAVE_EVERY_REQUEST = True

UNFOLD = {
    "SITE_TITLE": "Nepali Accounting",
    "SITE_HEADER": "Nepali Accounting",
}
