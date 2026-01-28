from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.conf import settings
import re
from typing import Tuple, List

from core.models import Profile


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


class NameUpdateForm(forms.Form):
    # 仅更新姓名（first_name/last_name），不更新用户名
    full_name = forms.CharField(
        max_length=150,
        label='新姓名 / New Name',
        widget=forms.TextInput(attrs={'placeholder': '请输入您的真实姓名 / Enter your full name'})
    )
    password = forms.CharField(
        label='当前密码 / Current password',
        widget=forms.PasswordInput(attrs={'placeholder': '请输入当前密码以确认 / Enter current password to confirm'})
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_full_name(self):
        full_name = (self.cleaned_data.get('full_name') or '').strip()
        if not full_name:
            raise forms.ValidationError("请输入您的姓名")
        return full_name

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
