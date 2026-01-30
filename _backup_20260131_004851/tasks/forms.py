from django import forms
from django.db import models
from core.models import Profile
from projects.models import Project
from tasks.models import TaskTemplateVersion

class TaskTemplateForm(forms.ModelForm):
    class Meta:
        model = TaskTemplateVersion
        fields = ['name', 'project', 'role', 'title', 'content', 'url', 'is_shared']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 5, 'placeholder': '任务内容模板 / Task content template'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = Project.objects.filter(is_active=True).order_by('name')
        self.fields['name'].widget.attrs.update({'placeholder': '如：上线任务模板 / e.g., Release Task'})
        self.fields['title'].widget.attrs.update({'placeholder': '如：发布 v1.2 版本 / e.g., Release v1.2'})
        self.fields['content'].widget.attrs.update({'placeholder': '步骤/说明（中英）：\n- 检查部署包 / Check build\n- 预发验证 / Staging verify\n- 正式发布 / Production rollout'})
        self.fields['url'].widget.attrs.update({'placeholder': '可选：任务链接 / Optional task link'})

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
        instance: TaskTemplateVersion = super().save(commit=False)
        if created_by:
            instance.created_by = created_by
        base_qs = TaskTemplateVersion.objects.filter(
            name=instance.name,
            role=instance.role,
            project=instance.project,
        )
        max_version = base_qs.aggregate(models.Max('version')).get('version__max') or 0
        instance.version = max_version + 1
        if commit:
            instance.save()
        return instance
