import json
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import user_passes_test, login_required
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.core.paginator import Paginator
from core.models import Profile, SalaryHistory, Contract
from reports.models import Project
from audit.utils import log_action
from reports.services import teams as team_service
from core.utils import _admin_forbidden, _validate_file

def is_superuser(user):
    return user.is_superuser

@login_required
def personnel_list(request):
    """
    独立的人事管理页面 / Personnel Management Page
    仅超级管理员可访问 (Only Superuser)
    """
    if not request.user.is_superuser:
        return _admin_forbidden(request, "需要管理员权限 / Admin access required")

    q = (request.GET.get('q') or '').strip()
    role = (request.GET.get('role') or '').strip()
    project_id = request.GET.get('project')
    project_filter = int(project_id) if project_id and project_id.isdigit() else None
    
    # 获取成员列表
    qs = team_service.get_team_members(q=q, role=role, project_id=project_filter)
    
    # 额外筛选：状态
    status = (request.GET.get('status') or 'active').strip()
    if status == 'active':
        qs = qs.filter(profile__employment_status='active')
    elif status == 'terminated':
        qs = qs.filter(profile__employment_status='terminated')
    # 如果 status == 'all'，不过滤
    
    # 计算统计数据
    # 优化：将多次计数合并为单次查询
    from django.db.models import Count, Q
    
    total_users_qs = User.objects.all()
    now = timezone.now()
    
    stats_agg = total_users_qs.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(profile__employment_status='active')),
        terminated=Count('id', filter=Q(profile__employment_status='terminated')),
        new_hires=Count('id', filter=Q(profile__hire_date__month=now.month, profile__hire_date__year=now.year))
    )
    
    stats = {
        'total': stats_agg['total'],
        'active': stats_agg['active'],
        'terminated': stats_agg['terminated'],
        'new_hires': stats_agg['new_hires'],
    }
    
    # 分页处理
    try:
        per_page = int(request.GET.get('per_page', 20))
        if per_page not in [10, 20, 50, 100]:
            per_page = 20
    except (ValueError, TypeError):
        per_page = 20

    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # 筛选下拉框使用的项目列表 - 优化：仅获取 ID 和名称
    projects = Project.objects.filter(is_active=True).order_by('name').only('id', 'name')

    return render(request, 'reports/personnel_list.html', {
        'users': page_obj,
        'page_obj': page_obj,
        'per_page': per_page,
        'q': q,
        'role': role,
        'status': status,
        'project_filter': project_filter,
        'roles': Profile.ROLE_CHOICES,
        'total_count': qs.count(),
        'projects': projects,
        'stats': stats,
        'today_date': timezone.now().strftime('%Y-%m-%d'),
    })

from work_logs.models import Attendance

@login_required
def attendance_stats(request):
    """
    月度考勤统计 API
    GET /api/attendance/stats/?user_id=123&month=2023-10
    """
    user_id = request.GET.get('user_id')
    month_str = request.GET.get('month') # YYYY-MM

    if not user_id or not month_str:
        return JsonResponse({'error': 'Missing user_id or month'}, status=400)
    
    # 权限检查（目前仅限超级管理员）
    if not request.user.is_superuser:
         return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        year, month = map(int, month_str.split('-'))
        from calendar import monthrange
        start_date = date(year, month, 1)
        _, last_day = monthrange(year, month)
        end_date = date(year, month, last_day)
    except ValueError:
        return JsonResponse({'error': 'Invalid month format'}, status=400)

    attendances = Attendance.objects.filter(
        user_id=user_id,
        date__range=(start_date, end_date)
    ).select_related('report')

    records = []
    present_days = 0
    makeup_days = 0
    leave_days = 0

    for att in attendances:
        records.append({
            'date': att.date.isoformat(),
            'status': att.status,
            'report_id': att.report_id,
        })
        if att.status == 'present':
            present_days += 1
        elif att.status == 'makeup':
            makeup_days += 1
        elif att.status == 'leave':
            leave_days += 1
    
    return JsonResponse({
        'status': 'success',
        'data': {
            'user_id': user_id,
            'month': month_str,
            'present_days': present_days,
            'makeup_days': makeup_days,
            'leave_days': leave_days,
            'records': records
        }
    })

@user_passes_test(is_superuser)
@require_http_methods(["PUT", "POST"]) # Allow POST for FormData
def update_hr_info(request, user_id):
    """
    更新成员人事信息 (仅管理员)
    PUT/POST /api/admin/members/{id}/hr-info
    """
    try:
        if request.content_type and request.content_type.startswith('application/json'):
            data = json.loads(request.body)
        else:
            data = request.POST
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    user = get_object_or_404(User, pk=user_id)
    profile, created = Profile.objects.get_or_create(user=user)

    errors = {}

    # 1. 就职状态
    employment_status = data.get('employment_status')
    if employment_status and employment_status not in ['active', 'terminated']:
        errors['employment_status'] = '无效的状态 / Invalid status'

    # 2. 入职时间
    hire_date_str = data.get('hire_date')
    hire_date = None
    if hire_date_str:
        try:
            hire_date = datetime.strptime(hire_date_str, '%Y-%m-%d').date()
            if hire_date > timezone.now().date():
                errors['hire_date'] = '入职时间不能晚于今天 / Hire date cannot be in future'
        except ValueError:
            errors['hire_date'] = '日期格式错误 (YYYY-MM-DD) / Invalid date format'
    else:
        # 如果模型允许为空，则无需强制。但根据需求建议填写。
        pass

    # 3. 试用期（月）
    probation_months = data.get('probation_months')
    if probation_months is not None:
        try:
            pm = int(probation_months)
            if not (1 <= pm <= 6):
                errors['probation_months'] = '试用期必须在 1-6 个月之间 / Probation must be 1-6 months'
        except ValueError:
            errors['probation_months'] = '必须是整数 / Must be integer'

    # 4. 试用期薪资
    probation_salary = data.get('probation_salary')
    ps_val = None
    if probation_salary is not None:
        try:
            ps_val = Decimal(str(probation_salary))
            if ps_val <= 0:
                errors['probation_salary'] = '薪资必须大于 0 / Salary must be > 0'
        except (InvalidOperation, ValueError):
            errors['probation_salary'] = '无效的金额 / Invalid amount'

    # 5. 正式薪资
    official_salary = data.get('official_salary')
    os_val = None
    if official_salary is not None:
        try:
            os_val = Decimal(str(official_salary))
            # 宽松验证：允许正式薪资 >= 0
            if os_val < 0:
                 errors['official_salary'] = '薪资必须大于等于 0 / Salary must be >= 0'
        except (InvalidOperation, ValueError):
            errors['official_salary'] = '无效的金额 / Invalid amount'
            
    # 额外验证：正式薪资不能低于试用期薪资
    if ps_val is not None and os_val is not None:
        if os_val < ps_val:
             errors['official_salary'] = '正式薪资不能低于试用期薪资 / Official salary cannot be lower than probation'

    # 6. 离职时间
    resignation_date_str = data.get('resignation_date')
    resignation_date = None
    if resignation_date_str:
        try:
            resignation_date = datetime.strptime(resignation_date_str, '%Y-%m-%d').date()
            if hire_date and resignation_date <= hire_date:
                errors['resignation_date'] = '离职时间必须晚于入职时间 / Resignation must be after hire date'
        except ValueError:
            errors['resignation_date'] = '日期格式错误 (YYYY-MM-DD) / Invalid date format'

    # 7. 备注
    hr_note = data.get('hr_note')
    append_note = data.get('append_note', False)
    
    if hr_note is not None and len(hr_note) > 500:
        errors['hr_note'] = '备注过长 (Max 500) / Note too long'

    # 8. 货币单位
    salary_currency = data.get('salary_currency', 'CNY')
    if salary_currency not in ['CNY', 'USDT']:
        errors['salary_currency'] = '无效的货币 / Invalid currency'

    # 9. 中介信息验证
    intermediary_company = data.get('intermediary_company', '')
    intermediary_fee_amount = data.get('intermediary_fee_amount')
    intermediary_fee_currency = data.get('intermediary_fee_currency', 'CNY')

    # 转换金额为 Decimal 或 None
    ifa_val = None
    if intermediary_fee_amount is not None and str(intermediary_fee_amount).strip() != '':
        try:
            ifa_val = Decimal(str(intermediary_fee_amount))
            if ifa_val < 0:
                errors['intermediary_fee_amount'] = '中介费用必须 >= 0 / Fee must be >= 0'
            if ifa_val > Decimal('999999999.99'):
                errors['intermediary_fee_amount'] = '中介费用过大 / Fee too large'
        except (InvalidOperation, ValueError):
            errors['intermediary_fee_amount'] = '无效的金额 / Invalid amount'
    
    # 联合验证
    has_company = bool(intermediary_company and intermediary_company.strip())
    has_fee = ifa_val is not None and ifa_val > 0
    
    # 如果填写了公司，必须填写费用（需求：费用与货币必填）
    if has_company:
        if ifa_val is None:
             errors['intermediary_fee_amount'] = '填写中介费用时，必须同时填写中介公司与货币单位'
        # 货币检查
        if intermediary_fee_currency not in ['CNY', 'USDT']:
             errors['intermediary_fee_currency'] = '无效的货币 / Invalid currency'

    # 如果填写了费用，必须填写公司
    if has_fee:
        if not has_company:
            errors['intermediary_company'] = '填写中介费用时，必须同时填写中介公司与货币单位'
        if intermediary_fee_currency not in ['CNY', 'USDT']:
             errors['intermediary_fee_currency'] = '无效的货币 / Invalid currency'

    if errors:
        return JsonResponse({'status': 'error', 'errors': errors}, status=400)

    # 记录修改前的历史数据
    old_probation = profile.probation_salary
    old_official = profile.official_salary
    old_currency = profile.salary_currency
    old_status = profile.employment_status

    # 保存数据
    if employment_status: profile.employment_status = employment_status
    if hire_date: profile.hire_date = hire_date
    if probation_months is not None: profile.probation_months = int(probation_months)
    if ps_val is not None: profile.probation_salary = ps_val
    if os_val is not None: profile.official_salary = os_val
    profile.salary_currency = salary_currency
    
    # 保存中介信息
    profile.intermediary_company = intermediary_company if intermediary_company else None
    if ifa_val is not None:
        profile.intermediary_fee_amount = ifa_val
    else:
        profile.intermediary_fee_amount = None
    profile.intermediary_fee_currency = intermediary_fee_currency

    # 处理可选日期的清除（前端传空字符串）
    if 'resignation_date' in data: # 检查键是否存在以允许清除
        profile.resignation_date = resignation_date # 可以为 None
        
    if hr_note is not None:
        if append_note and profile.hr_note:
            profile.hr_note = f"{profile.hr_note}\n{hr_note}"
        else:
            profile.hr_note = hr_note
    
    # USDT 信息
    usdt_address = data.get('usdt_address')
    if usdt_address is not None:
        profile.usdt_address = usdt_address
        
    if request.FILES.get('usdt_qr_code'):
        # 验证图片
        is_valid, msg = _validate_file(request.FILES['usdt_qr_code'], max_size=5*1024*1024, allowed_extensions=['.jpg', '.png', '.jpeg'])
        if not is_valid:
             return JsonResponse({'status': 'error', 'errors': {'usdt_qr_code': msg}}, status=400)
        profile.usdt_qr_code = request.FILES['usdt_qr_code']
    
    profile.save()

    # 记录薪资变更历史（如有）
    new_probation = profile.probation_salary
    new_official = profile.official_salary
    new_currency = profile.salary_currency
    
    if (old_probation != new_probation or 
        old_official != new_official or 
        old_currency != new_currency):
        SalaryHistory.objects.create(
            user=user,
            old_probation=old_probation,
            new_probation=new_probation,
            old_official=old_official,
            new_official=new_official,
            currency=new_currency,
            reason=data.get('reason', 'HR Update'),
            changed_by=request.user
        )

    action_summary = f"hr_info_update user={user.username}"
    if old_status != 'active' and profile.employment_status == 'active':
        action_summary = f"Confirm Probation (转正) for {user.username}"
    elif old_status != 'terminated' and profile.employment_status == 'terminated':
        action_summary = f"Terminate Employee (离职) for {user.username}"

    log_action(request, 'update', action_summary, data=data)

    return JsonResponse({
        'status': 'success',
        'data': {
            'id': user.id,
            'employment_status': profile.employment_status,
            'hire_date': profile.hire_date.isoformat() if profile.hire_date else None,
            'probation_months': profile.probation_months,
            'probation_salary': str(profile.probation_salary) if profile.probation_salary else None,
            'official_salary': str(profile.official_salary) if profile.official_salary else None,
            'salary_currency': profile.salary_currency,
            'usdt_address': profile.usdt_address or '',
            'usdt_qr_code': profile.usdt_qr_code.url if profile.usdt_qr_code else '',
            'intermediary_company': profile.intermediary_company or '',
            'intermediary_fee_amount': str(profile.intermediary_fee_amount) if profile.intermediary_fee_amount else '',
            'intermediary_fee_currency': profile.intermediary_fee_currency,
            'resignation_date': profile.resignation_date.isoformat() if profile.resignation_date else None,
            'hr_note': profile.hr_note
        }
    })

# --- HR 新功能 ---

@user_passes_test(is_superuser)
def salary_history_list(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    history = user.salary_history.select_related('changed_by').all()
    
    data = []
    for h in history:
        data.append({
            'id': h.id,
            'old_probation': str(h.old_probation) if h.old_probation else None,
            'new_probation': str(h.new_probation) if h.new_probation else None,
            'old_official': str(h.old_official) if h.old_official else None,
            'new_official': str(h.new_official) if h.new_official else None,
            'currency': h.currency,
            'reason': h.reason,
            'changed_by': h.changed_by.username if h.changed_by else 'System',
            'created_at': h.created_at.strftime('%Y-%m-%d %H:%M')
        })
    return JsonResponse({'status': 'success', 'data': data})

@user_passes_test(is_superuser)
@require_http_methods(["GET"])
def contract_list(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    contracts = user.contracts.select_related('uploaded_by').all()
    
    data = []
    for c in contracts:
        data.append({
            'id': c.id,
            'name': c.original_filename,
            'url': c.file.url,
            'start_date': c.start_date.strftime('%Y-%m-%d') if c.start_date else None,
            'end_date': c.end_date.strftime('%Y-%m-%d') if c.end_date else None,
            'uploaded_by': c.uploaded_by.username if c.uploaded_by else 'System',
            'created_at': c.created_at.strftime('%Y-%m-%d')
        })
    return JsonResponse({'status': 'success', 'data': data})

@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def contract_upload(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    file = request.FILES.get('file')
    start_date_str = request.POST.get('start_date')
    end_date_str = request.POST.get('end_date')
    
    if not file:
        return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)
        
    is_valid, msg = _validate_file(file, max_size=10*1024*1024, allowed_extensions=['.pdf', '.doc', '.docx', '.jpg', '.png'])
    if not is_valid:
        return JsonResponse({'status': 'error', 'message': msg}, status=400)
        
    start_date = None
    end_date = None
    try:
        if start_date_str: start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        if end_date_str: end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid date format'}, status=400)
        
    contract = Contract.objects.create(
        user=user,
        file=file,
        original_filename=file.name,
        uploaded_by=request.user,
        start_date=start_date,
        end_date=end_date
    )
    
    return JsonResponse({
        'status': 'success',
        'id': contract.id,
        'url': contract.file.url,
        'name': contract.original_filename
    })

@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def contract_delete(request, contract_id):
    contract = get_object_or_404(Contract, pk=contract_id)
    # 检查权限（目前仅限超级管理员）
    contract.delete()
    return JsonResponse({'status': 'success'})
