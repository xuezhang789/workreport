import base64
import io
import secrets
from urllib.parse import urlencode

import qrcode
from django.conf import settings
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.cache import never_cache
from django_otp import devices_for_user, login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.models import MFARecoveryCode


def _safe_next(request):
    candidate = request.POST.get('next') or request.GET.get('next') or settings.LOGIN_REDIRECT_URL
    if url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return candidate
    return settings.LOGIN_REDIRECT_URL


def _confirmed_devices(user):
    return list(devices_for_user(user, confirmed=True))


def _attempt_key(user):
    return f'mfa-attempts:{user.pk}'


def _record_failed_attempt(user):
    key = _attempt_key(user)
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, timeout=settings.MFA_ATTEMPT_WINDOW_SECONDS)


def _too_many_attempts(user):
    return cache.get(_attempt_key(user), 0) >= settings.MFA_MAX_ATTEMPTS


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def mfa_setup(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden('MFA setup is restricted to privileged accounts.')
    confirmed = _confirmed_devices(request.user)
    if confirmed:
        return redirect('core:mfa_verify')

    device, _ = TOTPDevice.objects.get_or_create(
        user=request.user,
        name='primary',
        defaults={'confirmed': False},
    )
    if request.method == 'POST':
        if _too_many_attempts(request.user):
            return HttpResponse('Too many MFA attempts. Try again later.', status=429)
        token = (request.POST.get('token') or '').strip()
        if device.verify_token(token):
            device.confirmed = True
            device.save(update_fields=['confirmed'])
            recovery_codes = [secrets.token_hex(5).upper() for _ in range(10)]
            MFARecoveryCode.replace_for_user(request.user, recovery_codes)
            cache.delete(_attempt_key(request.user))
            otp_login(request, device)
            return render(request, 'registration/mfa_recovery_codes.html', {
                'recovery_codes': recovery_codes,
                'next': _safe_next(request),
            })
        messages.error(request, '验证码无效，请确认设备时间正确后重试。')
        _record_failed_attempt(request.user)

    image = qrcode.make(device.config_url)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    qr_data = base64.b64encode(buffer.getvalue()).decode('ascii')
    return render(request, 'registration/mfa_setup.html', {
        'device': device,
        'qr_data': qr_data,
        'next': _safe_next(request),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def mfa_verify(request):
    if not request.user.is_superuser:
        return redirect(_safe_next(request))
    devices = _confirmed_devices(request.user)
    if not devices:
        return redirect(f"{reverse('core:mfa_setup')}?{urlencode({'next': _safe_next(request)})}")
    if request.user.is_verified():
        return redirect(_safe_next(request))

    if request.method == 'POST':
        if _too_many_attempts(request.user):
            return HttpResponse('Too many MFA attempts. Try again later.', status=429)
        token = (request.POST.get('token') or '').strip().upper()
        verified_device = next((device for device in devices if device.verify_token(token)), None)
        if verified_device is None and MFARecoveryCode.consume(request.user, token):
            verified_device = devices[0]
        if verified_device is not None:
            cache.delete(_attempt_key(request.user))
            otp_login(request, verified_device)
            return redirect(_safe_next(request))
        _record_failed_attempt(request.user)
        messages.error(request, '验证码或恢复码无效。')
    return render(request, 'registration/mfa_verify.html', {'next': _safe_next(request)})


@login_required
@never_cache
@require_POST
def mfa_regenerate_recovery_codes(request):
    if not request.user.is_superuser or not request.user.is_verified():
        return HttpResponseForbidden('Verified privileged session required.')
    if not request.user.check_password(request.POST.get('password') or ''):
        messages.error(request, '当前密码不正确。')
        return redirect('core:account_settings')
    recovery_codes = [secrets.token_hex(5).upper() for _ in range(10)]
    MFARecoveryCode.replace_for_user(request.user, recovery_codes)
    return render(request, 'registration/mfa_recovery_codes.html', {
        'recovery_codes': recovery_codes,
        'next': reverse('core:account_settings'),
    })
