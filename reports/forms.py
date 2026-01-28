from django import forms
from django.db import models
from work_logs.models import ReportTemplateVersion
from projects.models import Project

class ReportTemplateForm(forms.ModelForm):
    class Meta:
        model = ReportTemplateVersion
        fields = ['name', 'role', 'project', 'content', 'placeholders', 'is_shared']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 6, 'placeholder': '模板正文 / Template content'}),
            'placeholders': forms.Textarea(attrs={'rows': 3, 'placeholder': '{"today_work": "..."}'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = Project.objects.filter(is_active=True).order_by('name')
        self.fields['name'].widget.attrs.update({'placeholder': '如：开发日报 / e.g., Daily Dev Report'})
        self.fields['content'].widget.attrs.update({'placeholder': '如：今日完成 / Today done ...\n明日计划 / Plan for tomorrow ...'})
        self.fields['placeholders'].widget.attrs.update({'placeholder': '{"date": "2025-01-01", "today_work": "完成接口开发 / Finished API dev", "tomorrow_plan": "联调与测试 / Integration & testing"}'})
        
        for name, field in self.fields.items():
            if name == 'is_shared':
                field.widget.attrs.update({'class': 'form-checkbox'})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({'class': 'form-select'})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({'class': 'form-input', 'style': 'font-family: monospace; font-size: 13px;'})
            else:
                field.widget.attrs.update({'class': 'form-input'})

    def save(self, created_by=None, commit=True):
        instance: ReportTemplateVersion = super().save(commit=False)
        if created_by:
            instance.created_by = created_by
        base_qs = ReportTemplateVersion.objects.filter(
            name=instance.name,
            role=instance.role,
            project=instance.project,
        )
        max_version = base_qs.aggregate(models.Max('version')).get('version__max') or 0
        instance.version = max_version + 1
        if commit:
            instance.save()
        return instance
