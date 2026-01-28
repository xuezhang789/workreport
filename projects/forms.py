from django import forms
from django.contrib.auth.models import User
from projects.models import Project, ProjectPhaseConfig

class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        full_name = obj.get_full_name()
        if full_name:
            return f"{full_name} ({obj.username})"
        return obj.username

class UserMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        full_name = obj.get_full_name()
        if full_name:
            return f"{full_name} ({obj.username})"
        return obj.username

class ProjectPhaseConfigForm(forms.ModelForm):
    class Meta:
        model = ProjectPhaseConfig
        fields = ['phase_name', 'progress_percentage', 'order_index', 'is_active']
        widgets = {
            'phase_name': forms.TextInput(attrs={'placeholder': '如：开发实施 / Implementation'}),
            'progress_percentage': forms.NumberInput(attrs={'min': 0, 'max': 100, 'placeholder': '0-100'}),
            'order_index': forms.NumberInput(attrs={'min': 0, 'placeholder': '排序 / Sort Order'}),
        }

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'code', 'description', 'start_date', 'end_date', 'sla_hours', 'owner', 'members', 'managers', 'is_active']
        field_classes = {
            'owner': UserChoiceField,
            'members': UserMultipleChoiceField,
            'managers': UserMultipleChoiceField,
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'members': forms.SelectMultiple(attrs={'size': 8}),
            'managers': forms.SelectMultiple(attrs={'size': 6}),
            'sla_hours': forms.NumberInput(attrs={'min': 1, 'placeholder': '项目级 SLA 提醒（小时）'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'placeholder': '开始日期 / Start'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'placeholder': '结束日期 / End'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].queryset = User.objects.filter(is_active=True).order_by('username')
        self.fields['members'].queryset = User.objects.filter(is_active=True).order_by('username')
        self.fields['managers'].queryset = User.objects.filter(is_active=True).order_by('username')
        # 显式启用多选并设置易于识别的 id，避免前端样式或组件覆盖成单选
        self.fields['members'].widget.attrs.update({'id': 'members-select', 'multiple': 'multiple'})
        self.fields['managers'].widget.attrs.update({'id': 'managers-select', 'multiple': 'multiple'})
        # 必填字段的双语必填提示
        self.fields['name'].required = True
        self.fields['code'].required = True
        self.fields['name'].error_messages['required'] = "项目名称必填 / Project name required"
        self.fields['code'].error_messages['required'] = "项目代码必填 / Project code required"
        self.fields['name'].widget.attrs.update({'placeholder': '项目名称 / Project name'})
        self.fields['code'].widget.attrs.update({'placeholder': '项目代码 / Project code'})
