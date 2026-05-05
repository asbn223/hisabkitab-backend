# config/celery.py
import os
from celery import Celery
from celery.signals import task_failure

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

app = Celery('nepali_accounting')

app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all registered apps
app.autodiscover_tasks()

# Beat schedule
app.conf.beat_schedule = {
    'process-sync-queue': {
        'task': 'apps.core.tasks.process_sync_queue',
        'schedule': 30.0,  # Every 30 seconds
    },
    'generate-daily-reports': {
        'task': 'apps.reports.tasks.generate_daily_reports',
        'schedule': 'crontab(hour=1, minute=0)',  # 1 AM daily
    },
    'cleanup-old-audit-logs': {
        'task': 'apps.audit.tasks.archive_old_logs',
        'schedule': 'crontab(hour=2, minute=0, day_of_week=0)',  # Weekly Sunday 2 AM
    },
}

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')


# @task_failure.connect
# def handle_task_failure(sender, task_id, exception, args, kwargs, traceback, einfo, **kw):
#     """Send notification on task failure."""
#     from sentry_sdk import capture_exception
#     capture_exception(exception)