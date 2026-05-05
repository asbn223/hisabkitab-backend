from rest_framework import serializers
from .models import SavedReport, ReportSchedule, ReportExport


class SavedReportSerializer(serializers.ModelSerializer):
    report_type_display = serializers.CharField(source='get_report_type_display', read_only=True)

    class Meta:
        model = SavedReport
        fields = [
            'id', 'name', 'report_type', 'report_type_display',
            'parameters', 'date_format', 'show_zero_balances',
            'compare_with_previous', 'is_favorite', 'created_at'
        ]
        read_only_fields = ['tenant']


class ReportScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportSchedule
        fields = '__all__'


class ReportExportSerializer(serializers.ModelSerializer):
    format_display = serializers.CharField(source='get_format_display', read_only=True)

    class Meta:
        model = ReportExport
        fields = [
            'id', 'report_type', 'format', 'format_display',
            'file', 'file_size', 'generated_at', 'download_count'
        ]