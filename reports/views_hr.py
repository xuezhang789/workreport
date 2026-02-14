import json
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from core.models import Profile
from audit.utils import log_action

def is_superuser(user):
    return user.is_superuser

@user_passes_test(is_superuser)
@require_http_methods(["PUT"])
def update_hr_info(request, user_id):
    """
    更新成员人事信息 (仅管理员)
    PUT /api/admin/members/{id}/hr-info
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    user = get_object_or_404(User, pk=user_id)
    profile, created = Profile.objects.get_or_create(user=user)

    errors = {}

    # 1. Employment Status
    employment_status = data.get('employment_status')
    if employment_status not in ['active', 'terminated']:
        errors['employment_status'] = '无效的状态 / Invalid status'

    # 2. Hire Date
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
        # Assuming hire_date is optional based on model (null=True), but requirements say "入职时间...需小于等于当前日期". 
        # If it's mandatory for "HR managed" users, we should enforce it?
        # Requirement: "入职时间（日期类型），格式YYYY-MM-DD，需小于等于当前日期" - implies it's required if set? 
        # Let's enforce format if provided.
        pass

    # 3. Probation Months
    probation_months = data.get('probation_months')
    if probation_months is not None:
        try:
            pm = int(probation_months)
            if not (1 <= pm <= 6):
                errors['probation_months'] = '试用期必须在 1-6 个月之间 / Probation must be 1-6 months'
        except ValueError:
            errors['probation_months'] = '必须是整数 / Must be integer'

    # 4. Probation Salary
    probation_salary = data.get('probation_salary')
    ps_val = None
    if probation_salary is not None:
        try:
            ps_val = Decimal(str(probation_salary))
            if ps_val <= 0:
                errors['probation_salary'] = '薪资必须大于 0 / Salary must be > 0'
        except (InvalidOperation, ValueError):
            errors['probation_salary'] = '无效的金额 / Invalid amount'

    # 5. Official Salary
    official_salary = data.get('official_salary')
    os_val = None
    if official_salary is not None:
        try:
            os_val = Decimal(str(official_salary))
            # Must be > probation salary if both exist
            if ps_val is not None and os_val <= ps_val:
                errors['official_salary'] = '正式薪资必须大于试用薪资 / Official salary must be > probation salary'
        except (InvalidOperation, ValueError):
            errors['official_salary'] = '无效的金额 / Invalid amount'

    # 6. Resignation Date
    resignation_date_str = data.get('resignation_date')
    resignation_date = None
    if resignation_date_str:
        try:
            resignation_date = datetime.strptime(resignation_date_str, '%Y-%m-%d').date()
            if hire_date and resignation_date <= hire_date:
                errors['resignation_date'] = '离职时间必须晚于入职时间 / Resignation must be after hire date'
        except ValueError:
            errors['resignation_date'] = '日期格式错误 (YYYY-MM-DD) / Invalid date format'

    # 7. Note
    hr_note = data.get('hr_note', '')
    if len(hr_note) > 500:
        errors['hr_note'] = '备注过长 (Max 500) / Note too long'

    # 8. Currency
    salary_currency = data.get('salary_currency', 'CNY')
    if salary_currency not in ['CNY', 'USDT']:
        errors['salary_currency'] = '无效的货币 / Invalid currency'

    # 9. Intermediary Validation
    intermediary_company = data.get('intermediary_company', '')
    intermediary_fee_amount = data.get('intermediary_fee_amount')
    intermediary_fee_currency = data.get('intermediary_fee_currency', 'CNY')

    # Convert amount to Decimal or None
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
    
    # Joint Validation
    has_company = bool(intermediary_company and intermediary_company.strip())
    has_fee = ifa_val is not None and ifa_val > 0
    
    # If company is set, fee must be set (requirement: intermediary_fee_amount and currency required)
    # Currency has default, so check amount.
    if has_company:
        if ifa_val is None:
             errors['intermediary_fee_amount'] = '填写中介费用时，必须同时填写中介公司与货币单位'
        # Currency check
        if intermediary_fee_currency not in ['CNY', 'USDT']:
             errors['intermediary_fee_currency'] = '无效的货币 / Invalid currency'

    # If fee > 0, company must be set
    if has_fee:
        if not has_company:
            errors['intermediary_company'] = '填写中介费用时，必须同时填写中介公司与货币单位'
        if intermediary_fee_currency not in ['CNY', 'USDT']:
             errors['intermediary_fee_currency'] = '无效的货币 / Invalid currency'

    if errors:
        return JsonResponse({'status': 'error', 'errors': errors}, status=400)

    # Save
    if employment_status: profile.employment_status = employment_status
    if hire_date: profile.hire_date = hire_date
    if probation_months is not None: profile.probation_months = int(probation_months)
    if ps_val is not None: profile.probation_salary = ps_val
    if os_val is not None: profile.official_salary = os_val
    profile.salary_currency = salary_currency
    
    # Intermediary Save
    profile.intermediary_company = intermediary_company if intermediary_company else None
    if ifa_val is not None:
        profile.intermediary_fee_amount = ifa_val
    else:
        profile.intermediary_fee_amount = None
    profile.intermediary_fee_currency = intermediary_fee_currency

    # Handle optional date clearing (if empty string sent?)
    # Frontend sends YYYY-MM-DD or empty.
    if 'resignation_date' in data: # Check existence to allow clearing
        profile.resignation_date = resignation_date # Can be None
        
    profile.hr_note = hr_note # XSS filtering is done on Frontend display, backend stores raw text usually. 
    # But django templates escape by default.
    
    profile.save()

    log_action(request, 'update', f"hr_info_update user={user.username}", data=data)

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
            'intermediary_company': profile.intermediary_company or '',
            'intermediary_fee_amount': str(profile.intermediary_fee_amount) if profile.intermediary_fee_amount else '',
            'intermediary_fee_currency': profile.intermediary_fee_currency,
            'resignation_date': profile.resignation_date.isoformat() if profile.resignation_date else None,
            'hr_note': profile.hr_note
        }
    })
