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
        
        # Performance Optimization: Don't load all users initially
        # 性能优化：初始化时不加载所有用户，避免大量数据导致页面卡顿
        
        # 1. Default: Empty QuerySet
        self.fields['owner'].queryset = User.objects.none()
        self.fields['members'].queryset = User.objects.none()
        self.fields['managers'].queryset = User.objects.none()

        # 2. Edit Mode: Load existing relations
        if self.instance.pk:
            self.fields['owner'].queryset = User.objects.filter(pk=self.instance.owner_id)
            self.fields['members'].queryset = self.instance.members.all()
            self.fields['managers'].queryset = self.instance.managers.all()

        # 3. POST / Validation Mode: Allow submitted IDs
        if self.data:
            owner_id = self.data.get('owner')
            member_ids = self.data.getlist('members')
            manager_ids = self.data.getlist('managers')

            # Use union of existing and submitted to ensure validation passes and data is preserved
            # Note: For simple validation, just filtering by submitted IDs is enough.
            # Django will validate that the submitted ID exists in the queryset.
            
            if owner_id:
                # Must include both new and old to support disabled fields fallback
                ids = [owner_id]
                if self.instance.pk and self.instance.owner_id:
                    ids.append(self.instance.owner_id)
                self.fields['owner'].queryset = User.objects.filter(pk__in=ids)
            
            if member_ids:
                # Union with existing members isn't strictly necessary for M2M unless disabled?
                # If disabled, Django ignores POST. But we should be safe.
                qs = User.objects.filter(pk__in=member_ids)
                if self.instance.pk:
                    qs = qs | self.instance.members.all()
                self.fields['members'].queryset = qs.distinct()
                
            if manager_ids:
                qs = User.objects.filter(pk__in=manager_ids)
                if self.instance.pk:
                    qs = qs | self.instance.managers.all()
                self.fields['managers'].queryset = qs.distinct()

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
