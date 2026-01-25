from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.conf import settings
from django.db import models
import re
from typing import Tuple, List

from .models import Profile, Project, ReportTemplateVersion, TaskTemplateVersion, ProjectPhaseConfig


class ProjectPhaseConfigForm(forms.ModelForm):
    class Meta:
        model = ProjectPhaseConfig
        fields = ['phase_name', 'progress_percentage', 'order_index', 'is_active']
        widgets = {
            'phase_name': forms.TextInput(attrs={'placeholder': '如：开发实施 / Implementation'}),
            'progress_percentage': forms.NumberInput(attrs={'min': 0, 'max': 100, 'placeholder': '0-100'}),
            'order_index': forms.NumberInput(attrs={'min': 0, 'placeholder': '排序 / Sort Order'}),
        }



class RegistrationForm(UserCreationForm):
    full_name = forms.CharField(
        max_length=150,
        required=False,
        label='姓名 / Full name',
        help_text='用于展示的姓名，可留空'
    )
    position = forms.ChoiceField(
        choices=Profile.ROLE_CHOICES,
        initial='dev',
        label='角色 / Role'
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "full_name", "position", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = (self.cleaned_data.get("full_name") or "").strip()
        if full_name:
            parts = full_name.split(None, 1)
            user.first_name = parts[0]
            if len(parts) > 1:
                user.last_name = parts[1]

        if commit:
            user.save()
            Profile.objects.create(user=user, position=self.cleaned_data["position"])
        return user

    def clean_password1(self):
        password = self.cleaned_data.get("password1") or ""
        min_score = getattr(settings, 'PASSWORD_MIN_SCORE', 3)
        score, missing = password_score_and_missing(password)
        if score < min_score:
            raise forms.ValidationError(
                f"密码强度不足（{score}/6）：缺少 {', '.join(missing)}，需满足至少 {min_score} 项"
            )
        return password


class PasswordUpdateForm(forms.Form):
    # 需要先校验原密码，再校验复杂度并二次确认
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '请输入当前密码 / Current password'}),
        label='当前密码 / Current password'
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '新密码，至少8位且包含大小写与数字'}),
        label='新密码 / New password'
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '再次输入新密码以确认'}),
        label='确认新密码 / Confirm new password'
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data.get('old_password') or ''
        if not self.user.check_password(old_password):
            raise forms.ValidationError("原密码不正确 / Incorrect current password")
        return old_password

    def clean_new_password1(self):
        password = self.cleaned_data.get('new_password1') or ''
        missing = []
        if len(password) < 8:
            missing.append("至少 8 位")
        if not re.search(r'[A-Z]', password):
            missing.append("包含大写字母")
        if not re.search(r'[a-z]', password):
            missing.append("包含小写字母")
        if not re.search(r'[0-9]', password):
            missing.append("包含数字")
        if missing:
            raise forms.ValidationError(f"新密码需同时满足：{', '.join(missing)}")
        password_validation.validate_password(password, self.user)
        return password

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')
        if new_password1 and new_password2 and new_password1 != new_password2:
            self.add_error('new_password2', "两次输入的新密码不一致")
        return cleaned_data


class UsernameUpdateForm(forms.Form):
    # 仅更新用户名，校验唯一性与合法字符
    username = forms.CharField(
        max_length=150,
        label='用户名 / Username',
        widget=forms.TextInput(attrs={'placeholder': '新的用户名 / New username'})
    )
    password = forms.CharField(
        label='当前密码 / Current password',
        widget=forms.PasswordInput(attrs={'placeholder': '请输入当前密码以确认 / Enter current password to confirm'})
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if not username:
            raise forms.ValidationError("请输入新的用户名")
        if User.objects.filter(username__iexact=username).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("该用户名已被占用 / Username already exists")
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password') or ''
        if not self.user.check_password(password):
            raise forms.ValidationError("当前密码不正确 / Incorrect current password")
        return password


class EmailVerificationRequestForm(forms.Form):
    # 第一步：提交邮箱用于发送验证码
    email = forms.EmailField(
        label='邮箱 / Email',
        widget=forms.EmailInput(attrs={'placeholder': 'name@example.com'})
    )


class EmailVerificationConfirmForm(forms.Form):
    # 第二步：校验邮箱 + 验证码
    email = forms.EmailField(
        label='邮箱 / Email',
        widget=forms.EmailInput(attrs={'placeholder': 'name@example.com'})
    )
    code = forms.CharField(
        max_length=6,
        min_length=4,
        label='验证码 / Verification code',
        widget=forms.TextInput(attrs={'placeholder': '6位验证码'})
    )

    def clean_code(self):
        raw = (self.cleaned_data.get('code') or '').strip()
        # 允许粘贴时夹杂空格/非数字字符，自动提取数字后校验
        code = re.sub(r'\D', '', raw)
        if not re.match(r'^\d{4,6}$', code):
            raise forms.ValidationError("验证码格式不正确")
        return code


def password_score_and_missing(password: str) -> Tuple[int, List[str]]:
    """返回密码评分与缺失项说明。"""
    checks = [
        ('长度≥8', len(password) >= 8),
        ('长度≥12', len(password) >= 12),
        ('大写字母', bool(re.search(r'[A-Z]', password))),
        ('小写字母', bool(re.search(r'[a-z]', password))),
        ('数字', bool(re.search(r'[0-9]', password))),
        ('符号', bool(re.search(r'[^A-Za-z0-9]', password))),
    ]
    score = sum(1 for _, ok in checks if ok)
    missing = [label for label, ok in checks if not ok]
    return score, missing


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'code', 'description', 'start_date', 'end_date', 'sla_hours', 'owner', 'members', 'managers', 'is_active']
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
        self.fields['owner'].queryset = User.objects.order_by('username')
        self.fields['members'].queryset = User.objects.order_by('username')
        self.fields['managers'].queryset = User.objects.order_by('username')
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
