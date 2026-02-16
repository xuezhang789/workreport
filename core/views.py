import json
import time
import random
import os
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, get_user_model, update_session_auth_hash
from django.http import JsonResponse, StreamingHttpResponse
from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.utils import timezone
from django.db.models import Q, Count
from django.urls import reverse

from audit.utils import log_action
from core.forms import (
    RegistrationForm, 
    NameUpdateForm, 
    PasswordUpdateForm, 
    EmailVerificationRequestForm, 
    EmailVerificationConfirmForm
)
from core.utils import _throttle, _admin_forbidden, _friendly_forbidden
from core.permissions import has_manage_permission
from work_logs.models import DailyReport
from core.models import ExportJob
from projects.models import Project
from reports.utils import get_accessible_projects, get_manageable_projects

def register(request):
    if request.user.is_authenticated:
        return redirect('reports:workbench')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('reports:workbench')
    else:
        form = RegistrationForm()

    return render(request, 'registration/register.html', {
        'form': form,
        'password_min_score': getattr(settings, 'PASSWORD_MIN_SCORE', 3),
    })


def logout_view(request):
    """
    Allow POST logout for security. GET shows a confirmation page.
    """
    if request.method == 'POST':
        logout(request)
        return render(request, 'registration/logged_out.html')
    
    # If GET, show confirmation page to prevent CSRF logout
    if request.user.is_authenticated:
        return render(request, 'registration/logout_confirm.html')
        
    return render(request, 'registration/logged_out.html')


from django.core.validators import validate_email
from django.core.exceptions import ValidationError

@login_required
def send_email_code_api(request):
    """API for sending email verification code."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip()
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not email:
        return JsonResponse({'error': '请输入邮箱地址 / Please enter email address'}, status=400)

    # Security: Use Django's robust validator
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'error': '邮箱格式不正确 / Invalid email format'}, status=400)

    user = request.user
    UserModel = get_user_model()
    
    # Check availability
    if UserModel.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        return JsonResponse({'error': '该邮箱已被其他账号使用 / Email already in use'}, status=400)
    
    if email.lower() == (user.email or '').lower():
         return JsonResponse({'error': '该邮箱已绑定，无需重复验证 / Email already bound'}, status=400)

    # Cooldown check
    cooldown = 60
    now_ts = time.time()
    last_send = request.session.get('email_verification_last_send') or 0
    if now_ts - last_send < cooldown:
        remain = int(cooldown - (now_ts - last_send))
        return JsonResponse({'error': f'发送过于频繁，请 {remain} 秒后再试 / Too frequent, try again in {remain}s'}, status=429)

    code = f"{random.randint(100000, 999999)}"
    subject = "邮箱验证 / Email verification code"
    body = (
        f"您的验证码(your code)：{code}\n"
        f"10 分钟内有效，请勿泄露。If you did not request this, please ignore."
    )
    
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as exc:
        log_action(request, 'error', f"send email code failed to {email}", data={'error': str(exc)})
        return JsonResponse({'error': '验证码发送失败，请联系管理员 / Failed to send email'}, status=500)

    # Save to session
    request.session['email_verification'] = {
        'email': email,
        'code': code,
        'expires_at': time.time() + 600,
    }
    request.session['email_verification_last_send'] = now_ts
    request.session.modified = True
    
    log_action(request, 'update', f"send email code to {email}")
    
    msg = f"验证码已发送至 {email}"
    if settings.DEBUG:
        msg += f" (Code: {code})"
        
    return JsonResponse({'success': True, 'message': msg})


@login_required
def account_settings(request):
    """个人中心：姓名、密码与邮箱设置。"""
    user = request.user
    UserModel = get_user_model()
    name_form = NameUpdateForm(user=user, initial={'full_name': user.get_full_name()})
    password_form = PasswordUpdateForm(user=user)
    email_request_form = EmailVerificationRequestForm(initial={'email': user.email})
    email_confirm_form = EmailVerificationConfirmForm(initial={'email': user.email})

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'change_name':
            name_form = NameUpdateForm(user=user, data=request.POST)
            if name_form.is_valid():
                full_name = name_form.cleaned_data['full_name']
                parts = full_name.split(None, 1)
                user.first_name = parts[0]
                user.last_name = parts[1] if len(parts) > 1 else ''
                user.save(update_fields=['first_name', 'last_name'])
                messages.success(request, "姓名已更新 / Name updated successfully")
                log_action(request, 'update', f"name updated to {full_name}")
                return redirect('core:account_settings')
            
        elif action == 'change_password':
            password_form = PasswordUpdateForm(user=user, data=request.POST)
            if password_form.is_valid():
                new_password = password_form.cleaned_data['new_password1']
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)  # Keep user logged in
                log_action(request, 'update', "password changed")
                messages.success(request, "密码已更新 / Password updated successfully")
                return redirect('core:account_settings')

        elif action == 'update_email':
            email_confirm_form = EmailVerificationConfirmForm(data=request.POST)
            if email_confirm_form.is_valid():
                email = email_confirm_form.cleaned_data['email']
                code = email_confirm_form.cleaned_data['code']
                pending = request.session.get('email_verification') or {}
                
                if not pending or pending.get('email') != email:
                    messages.error(request, "请先获取该邮箱的验证码 / Please request code first")
                elif pending.get('expires_at', 0) < time.time():
                    messages.error(request, "验证码已过期 / Code expired")
                elif str(pending.get('code')) != str(code):
                    messages.error(request, "验证码不正确 / Invalid code")
                elif UserModel.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                    messages.error(request, "邮箱已被其他账号使用 / Email already in use")
                else:
                    user.email = email
                    user.save(update_fields=['email'])
                    request.session.pop('email_verification', None)
                    request.session.modified = True
                    
                    if hasattr(user, 'profile'):
                        user.profile.email_verified = True
                        user.profile.save()

                    messages.success(request, "邮箱已更新并完成验证 / Email updated and verified")
                    log_action(request, 'update', f"email updated to {email}")
                    return redirect('core:account_settings')
            else:
                messages.error(request, "输入有误，请检查 / Invalid input")

    # Calculate user statistics
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    user_reports = DailyReport.objects.filter(user=user)
    week_reports = user_reports.filter(date__gte=week_start)
    month_reports = user_reports.filter(date__gte=month_start)
    
    # Statistics
    week_report_count = week_reports.count()
    month_report_count = month_reports.count()
    total_report_count = user_reports.count()
    
    # Calculate completion rate (reports submitted vs expected)
    expected_week_reports = 7  # Assuming 7 days a week
    completion_rate = min(100, int((week_report_count / expected_week_reports) * 100)) if expected_week_reports > 0 else 0
    
    # Project participation
    project_count = get_accessible_projects(user).count()
    
    # Average completion time (placeholder - would need timestamp data)
    avg_completion_time = 2.5  # hours (placeholder)
    
    pending_email = request.session.get('email_verification')
    context = {
        'name_form': name_form,
        'password_form': password_form,
        'email_request_form': email_request_form,
        'email_confirm_form': email_confirm_form,
        'pending_email': pending_email,
        'password_min_score': getattr(settings, 'PASSWORD_MIN_SCORE', 3),
        # Statistics data
        'week_report_count': week_report_count,
        'month_report_count': month_report_count,
        'total_report_count': total_report_count,
        'completion_rate': completion_rate,
        'project_count': project_count,
        'avg_completion_time': avg_completion_time,
    }
    return render(request, 'registration/account_settings.html', context)


@login_required
def user_search_api(request):
    """人员远程搜索，用于任务指派等场景。"""
    # Allow participants to search users if they have any accessible project
    accessible_projects = get_accessible_projects(request.user)
    if not has_manage_permission(request.user) and not accessible_projects.exists():
        return _admin_forbidden(request)

    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    if _throttle(request, 'user_search_ts', min_interval=0.2):
        return JsonResponse({'error': '请求过于频繁'}, status=429)
    q = (request.GET.get('q') or '').strip()
    project_id = request.GET.get('project_id')
    User = get_user_model()
    
    if project_id and project_id.isdigit():
        # Project specific search
        from projects.models import Project
        
        # Security: Check if user has access to this project
        accessible_projects = get_accessible_projects(request.user)
        # accessible_projects already filters by permission (including superuser check)
        if not accessible_projects.filter(id=project_id).exists():
            return JsonResponse({'error': 'Project not accessible'}, status=403)
            
        try:
            project = Project.objects.get(pk=project_id)
            # Members + Managers + Owner
            qs = User.objects.filter(
                Q(project_memberships=project) |
                Q(managed_projects=project) |
                Q(owned_projects=project)
            ).distinct()
        except Project.DoesNotExist:
             qs = User.objects.none()
    elif has_manage_permission(request.user) or get_manageable_projects(request.user).exists():
        qs = User.objects.all()
    else:
        # Limit to users in accessible projects
        accessible_projects = get_accessible_projects(request.user)
        qs = User.objects.filter(
            Q(project_memberships__in=accessible_projects) |
            Q(managed_projects__in=accessible_projects) |
            Q(owned_projects__in=accessible_projects)
        ).distinct()

    if q:
        qs = qs.filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(email__icontains=q)
        )
        
    users = qs.select_related('profile').order_by('username')[:20]
    data = []
    
    # Pre-fetch roles if project_id is provided?
    # Or just use general profile info. Requirement: Avatar, Name, Role Tag (Owner/Admin/Member), Dept
    
    for u in users:
        full_name = u.get_full_name()
        display_name = f"{full_name} ({u.username})" if full_name else u.username
        if u.email:
            display_name += f" - {u.email}"
            
        role_label = 'Member'
        if project_id and project_id.isdigit():
            if u.id == project.owner_id:
                role_label = 'Owner'
            elif project.managers.filter(id=u.id).exists():
                role_label = 'Admin'
                
        # Department
        dept = u.profile.get_position_display() if hasattr(u, 'profile') else ''
        avatar = u.profile.avatar.url if hasattr(u, 'profile') and hasattr(u.profile, 'avatar') and u.profile.avatar else ''
        
        data.append({
            'id': u.id,
            'name': full_name or u.username,
            'username': u.username,
            'email': u.email,
            'text': display_name,
            'role': role_label,
            'department': dept,
            'avatar': avatar
        })
    return JsonResponse({'results': data})


def username_check_api(request):
    """实时检查用户名是否可用。"""
    # Allow anonymous users to check username availability for registration
         
    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    if _throttle(request, 'username_check_ts', min_interval=0.4):
        return JsonResponse({'error': '请求过于频繁'}, status=429)  # 简易节流防抖
    username = (request.GET.get('username') or '').strip()
    if not username:
        return JsonResponse({'available': False, 'reason': '请输入要检测的用户名 / Please enter a username to check'}, status=400)
        
    User = get_user_model()
    # Check if exists
    if User.objects.filter(username__iexact=username).exists():
        return JsonResponse({'available': False, 'reason': '用户名已存在 / Username already taken'})
        
    return JsonResponse({'available': True})

@login_required
def export_job_status(request, job_id: int):
    job = get_object_or_404(ExportJob, id=job_id, user=request.user)
    if job.expires_at and job.expires_at < timezone.now():
        job.status = 'failed'
        job.message = '导出已过期 / Export expired'
        job.save(update_fields=['status', 'message', 'updated_at'])
        if job.file_path and os.path.exists(job.file_path):
            try:
                os.remove(job.file_path)
            except OSError:
                pass
    data = {
        'job_id': job.id,
        'status': job.status,
        'progress': job.progress,
        'message': job.message,
        'download_url': reverse('core:export_job_download', args=[job.id]) if job.status == 'done' else '',
    }
    return JsonResponse(data)


@login_required
def export_job_download(request, job_id: int):
    job = get_object_or_404(ExportJob, id=job_id, user=request.user, status='done')
    if job.expires_at and job.expires_at < timezone.now():
        return _friendly_forbidden(request, "文件已过期，请重新导出 / File expired, please export again")
    if not job.file_path or not os.path.exists(job.file_path):
        return _friendly_forbidden(request, "文件不存在 / File missing")
    filename = f"{job.export_type}.csv"
    def file_iter(path):
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    yield chunk
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    response = StreamingHttpResponse(file_iter(job.file_path), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
