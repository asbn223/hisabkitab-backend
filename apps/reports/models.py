"""
Financial reporting models and saved report configurations.
"""
from decimal import Decimal
from django.db import models

from apps.tenants.models import Tenant
from core.db.fields import FiscalDecimalField


class SavedReport(models.Model):
    """
    User-saved report configurations.
    """
    REPORT_TYPES = [
        ('trial_balance', 'Trial Balance'),
        ('profit_loss', 'Profit & Loss'),
        ('balance_sheet', 'Balance Sheet'),
        ('cash_flow', 'Cash Flow Statement'),
        ('ledger', 'General Ledger'),
        ('bank_reconciliation', 'Bank Reconciliation'),
        ('vat_report', 'VAT Report'),
        ('tds_report', 'TDS Report'),
        ('receivables', 'Receivables Aging'),
        ('payables', 'Payables Aging'),
        ('inventory', 'Inventory Report'),
        ('sales', 'Sales Report'),
        ('purchase', 'Purchase Report'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='saved_reports'
    )

    name = models.CharField(max_length=255)
    report_type = models.CharField(max_length=30, choices=REPORT_TYPES)

    # Filter parameters (JSON)
    parameters = models.JSONField(default=dict, blank=True)

    # Display preferences
    date_format = models.CharField(
        max_length=10,
        choices=[('ad', 'Gregorian (AD)'), ('bs', 'Bikram Sambat (BS)')],
        default='bs'
    )
    show_zero_balances = models.BooleanField(default=False)
    compare_with_previous = models.BooleanField(default=False)

    is_favorite = models.BooleanField(default=False)
    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reports_savedreport'
        unique_together = [('tenant', 'name')]

    def __str__(self):
        return self.name


class ReportSchedule(models.Model):
    """
    Scheduled automatic report generation.
    """
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='report_schedules'
    )
    saved_report = models.ForeignKey(
        SavedReport,
        on_delete=models.CASCADE,
        related_name='schedules'
    )

    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    recipients = models.JSONField(default=list)  # List of email addresses
    last_run = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reports_reportschedule'


class ReportExport(models.Model):
    """
    Track generated report exports.
    """
    FORMAT_CHOICES = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('csv', 'CSV'),
        ('json', 'JSON'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='report_exports'
    )
    report_type = models.CharField(max_length=30)
    parameters = models.JSONField()
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES)

    file = models.FileField(upload_to='reports/%Y/%m/', blank=True)
    file_size = models.IntegerField(default=0)

    generated_by = models.CharField(max_length=255, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    download_count = models.IntegerField(default=0)

    class Meta:
        db_table = 'reports_reportexport'
        ordering = ['-generated_at']