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
from django.core.paginator import Paginator
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
from core.models import ExportJob, Invitation
from projects.models import Project
from reports.utils import get_accessible_projects, get_manageable_projects
import uuid

from django.db import transaction, IntegrityError

import logging

logger = logging.getLogger(__name__)

@transaction.non_atomic_requests
def register(request):
    """
    使用邀请码注册。
    """
    # 频率限制：防止暴力破解邀请码
    ip = request.META.get('REMOTE_ADDR')
    if _throttle(request, f'register_attempt_{ip}', max_requests=10, period=60):
         return render(request, '429.html', {'message': '注册尝试过于频繁，请稍后再试 / Too many registration attempts, please try again later'}, status=429)

    if request.user.is_authenticated:
        return redirect('reports:workbench')

    invitation_code = request.GET.get('code', '').strip()
    invitation = None
    
    if invitation_code:
        try:
            invitation = Invitation.objects.get(code=invitation_code)
            if not invitation.is_valid:
                # UX: 为 GET 请求提供具体反馈，但要小心
                messages.error(request, "邀请码无效或已过期 / Invitation code invalid or expired")
                invitation = None
        except Invitation.DoesNotExist:
            messages.error(request, "邀请码无效 / Invitation code invalid")
            invitation = None

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        code_input = request.POST.get('invitation_code', '').strip()
        
        try:
            with transaction.atomic():
                # 修复竞态条件：锁定行
                try:
                    valid_invite = Invitation.objects.select_for_update().get(code=code_input)
                except Invitation.DoesNotExist:
                    raise Invitation.DoesNotExist

                if not valid_invite.is_valid:
                    raise Invitation.DoesNotExist # 视为未找到以防止枚举
                
                # 如果邀请指定了邮箱，则验证邮箱
                email_input = form.data.get('email', '').strip()
                if valid_invite.email and valid_invite.email.lower() != email_input.lower():
                     form.add_error('email', "该邀请码仅限特定邮箱使用 / Invitation code is restricted to a specific email")
                     raise ValueError("Email mismatch")

                if form.is_valid():
                    user = form.save()
                    
                    # 将邀请标记为已使用
                    valid_invite.status = 'used'
                    valid_invite.used_at = timezone.now()
                    valid_invite.registered_user = user
                    valid_invite.save()
                    
                    login(request, user)
                    messages.success(request, "注册成功！欢迎加入。 / Registration successful! Welcome.")
                    return redirect('reports:workbench')
                    
        except Invitation.DoesNotExist:
            form.add_error(None, "邀请码无效 / Invitation code invalid")
        except ValueError:
            pass # 表单错误已添加
        except Exception as e:
            # 捕获意外错误
            form.add_error(None, "注册失败，请稍后重试 / Registration failed, please try again")
            logger.error(f"Register Error: {e}", exc_info=True)

    else:
        # 如果存在邀请，预填充邮箱
        initial_data = {}
        if invitation and invitation.email:
            initial_data['email'] = invitation.email
        form = RegistrationForm(initial=initial_data)

    return render(request, 'registration/register.html', {
        'form': form,
        'invitation_code': invitation_code if invitation else '',
        'password_min_score': getattr(settings, 'PASSWORD_MIN_SCORE', 3),
    })

@login_required
def invitation_list(request):
    """列表和创建邀请。"""
    # 检查权限（例如：管理员或经理）
    if not (request.user.is_superuser or has_manage_permission(request.user)):
        return _friendly_forbidden(request, "无权管理邀请 / No permission to manage invitations")

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            email = request.POST.get('email', '').strip()
            # 生成唯一代码并重试
            max_retries = 5
            for _ in range(max_retries):
                code = uuid.uuid4().hex[:12].upper() # 增加长度到 12 以防止枚举
                if not Invitation.objects.filter(code=code).exists():
                    Invitation.objects.create(
                        code=code,
                        inviter=request.user,
                        email=email if email else None
                    )
                    messages.success(request, "邀请码已生成 / Invitation code generated")
                    return redirect('core:invitation_list')
            
            messages.error(request, "生成邀请码失败，请重试 / Failed to generate code, please try again")
    
    # 优化：为头像选择关联的 profile
    invitations = Invitation.objects.filter(inviter=request.user).select_related('registered_user', 'registered_user__profile').order_by('-created_at')
    
    # 分页
    try:
        per_page = int(request.GET.get('per_page', 20))
        if per_page not in [10, 20, 50, 100]:
            per_page = 20
    except (ValueError, TypeError):
        per_page = 20

    paginator = Paginator(invitations, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    return render(request, 'core/invitation_list.html', {
        'invitations': page_obj,
        'page_obj': page_obj,
        'per_page': per_page,
    })


def logout_view(request):
    """
    为了安全起见，允许 POST 注销。GET 显示确认页面。
    """
    if request.method == 'POST':
        logout(request)
        return render(request, 'registration/logged_out.html')
    
    # 如果是 GET，显示确认页面以防止 CSRF 注销
    if request.user.is_authenticated:
        return render(request, 'registration/logout_confirm.html')
        
    return render(request, 'registration/logged_out.html')


from django.core.validators import validate_email
from django.core.exceptions import ValidationError

@login_required
def send_email_code_api(request):
    """发送邮箱验证码的 API。"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip()
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not email:
        return JsonResponse({'error': '请输入邮箱地址 / Please enter email address'}, status=400)

    # 安全：使用 Django 的健壮验证器
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'error': '邮箱格式不正确 / Invalid email format'}, status=400)

    user = request.user
    UserModel = get_user_model()
    
    # 检查可用性
    if UserModel.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        return JsonResponse({'error': '该邮箱已被其他账号使用 / Email already in use'}, status=400)
    
    if email.lower() == (user.email or '').lower():
         return JsonResponse({'error': '该邮箱已绑定，无需重复验证 / Email already bound'}, status=400)

    # 冷却检查
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

    # 保存到会话
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
                update_session_auth_hash(request, user)  # 保持用户登录状态
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

    # 计算用户统计数据
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    user_reports = DailyReport.objects.filter(user=user)
    week_reports = user_reports.filter(date__gte=week_start)
    month_reports = user_reports.filter(date__gte=month_start)
    
    # 统计数据
    week_report_count = week_reports.count()
    month_report_count = month_reports.count()
    total_report_count = user_reports.count()
    
    # 计算完成率（提交的日报与预期的对比）
    expected_week_reports = 7  # 假设每周 7 天
    completion_rate = min(100, int((week_report_count / expected_week_reports) * 100)) if expected_week_reports > 0 else 0
    
    # 项目参与度
    project_count = get_accessible_projects(user).count()
    
    # 平均完成时间（占位符 - 需要时间戳数据）
    avg_completion_time = 2.5  # 小时（占位符）
    
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
def global_search(request):
    """
    全局搜索：搜索项目、任务和日报。
    支持简单的数据库模糊查询。
    """
    q = request.GET.get('q', '').strip()
    if not q:
        return render(request, 'core/search_results.html', {'query': q, 'results': {}})
        
    results = {
        'projects': [],
        'tasks': [],
        'reports': []
    }
    
    # 1. 搜索项目
    # 仅搜索有权限的项目
    accessible_projects = get_accessible_projects(request.user)
    projects = accessible_projects.filter(
        Q(name__icontains=q) | 
        Q(code__icontains=q) |
        Q(description__icontains=q)
    ).select_related('owner', 'current_phase').distinct()[:10]
    results['projects'] = projects
    
    # 2. 搜索任务
    # 搜索用户可访问的任务：自己创建的、负责的、协作的、或所在项目的
    # 简化逻辑：如果在可访问的项目中，就可以搜索到任务
    from tasks.models import Task
    tasks = Task.objects.filter(
        project__in=accessible_projects
    ).filter(
        Q(title__icontains=q) |
        Q(content__icontains=q) |
        Q(id__icontains=q) # 支持搜 ID
    ).select_related('project', 'user', 'status').distinct()[:20]
    results['tasks'] = tasks
    
    # 3. 搜索日报
    # 搜索自己提交的，或者管理的项目的日报
    # 管理员可搜所有？或者按权限
    # 简单起见，搜索自己能看到的日报
    # 逻辑：如果是项目管理员，可以看到项目成员的日报；如果是普通成员，看自己和同项目？
    # 复用 reports.utils.get_manageable_projects ?
    
    # 这里使用一个简化的权限：
    # - 自己的日报
    # - 自己管理的项目的日报
    manageable_projects = get_manageable_projects(request.user)
    
    reports = DailyReport.objects.filter(
        Q(user=request.user) |
        Q(projects__in=manageable_projects)
    ).filter(
        Q(content__icontains=q) |
        Q(plan_next_day__icontains=q)
    ).select_related('user').prefetch_related('projects').distinct()[:10]
    
    results['reports'] = reports
    
    return render(request, 'core/search_results.html', {
        'query': q,
        'results': results,
        'total_count': len(projects) + len(tasks) + len(reports)
    })

@login_required
def user_search_api(request):
    """人员远程搜索，用于任务指派等场景。"""
    # 允许参与者搜索用户，如果他们有任何可访问的项目
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
    
    # 调试日志
    # print(f"User Search: user={request.user}, superuser={request.user.is_superuser}, project_id={project_id}")
    
    if project_id and project_id.isdigit():
        # 项目特定搜索
        from projects.models import Project
        
        # 安全：检查用户是否可以访问此项目
        accessible_projects = get_accessible_projects(request.user)
        # accessible_projects 已经过滤了权限（包括超级用户检查）
        if not accessible_projects.filter(id=project_id).exists():
            return JsonResponse({'error': 'Project not accessible'}, status=403)
            
        try:
            project = Project.objects.get(pk=project_id)
            # 成员 + 经理 + 拥有者
            qs = User.objects.filter(
                Q(project_memberships=project) |
                Q(managed_projects=project) |
                Q(owned_projects=project)
            ).distinct()
        except Project.DoesNotExist:
             qs = User.objects.none()
    else:
        # 全局搜索（上下文：添加成员，或管理员搜索）
        # 确定用户是否有权限搜索所有用户
        can_search_all = (
            request.user.is_superuser or
            request.user.is_staff or
            has_manage_permission(request.user) or 
            get_manageable_projects(request.user).exists() or
            request.user.owned_projects.exists() or
            request.user.managed_projects.exists()
        )
        
        if can_search_all:
            qs = User.objects.all()
        else:
            # 限制为可访问项目中的用户
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
    
    # 如果提供了 project_id，是否预取角色？
    # 或者只使用一般的个人资料信息。需求：头像、姓名、角色标签（拥有者/管理员/成员）、部门
    
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
                
        # 部门
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


@login_required
def username_check_api(request):
    """实时检查用户名是否可用。"""
    # 安全修复：需要登录以防止枚举
         
    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    if _throttle(request, 'username_check_ts', min_interval=0.4):
        return JsonResponse({'error': '请求过于频繁'}, status=429)  # 简易节流防抖
    username = (request.GET.get('username') or '').strip()
    if not username:
        return JsonResponse({'available': False, 'reason': '请输入要检测的用户名 / Please enter a username to check'}, status=400)
        
    User = get_user_model()
    # 检查是否存在
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
