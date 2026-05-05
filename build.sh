#!/usr/bin/env bash
set -o errexit

python -m pip install --upgrade pip
pip install -r requirements.txt

# Create logs directory for RotatingFileHandler
mkdir -p logs

python manage.py collectstatic --no-input
python manage.py migrate