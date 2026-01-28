import os
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import send_mail, get_connection
from django.conf import settings


class Command(BaseCommand):
    help = "Send a quick test email using current Django email settings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            dest="recipient",
            default=os.environ.get("TEST_EMAIL_TO"),
            help="Recipient email address (default from TEST_EMAIL_TO env or EMAIL_HOST_USER).",
        )
        parser.add_argument(
            "--from",
            dest="sender",
            default=None,
            help="Override sender address (default: DEFAULT_FROM_EMAIL or EMAIL_HOST_USER).",
        )
        parser.add_argument(
            "--backend",
            dest="backend",
            default=None,
            help="Optional email backend to use (fallback to settings.EMAIL_BACKEND).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=10,
            help="SMTP timeout seconds (default: 10).",
        )
        parser.add_argument(
            "--subject",
            default="SMTP connectivity test",
            help="Email subject.",
        )
        parser.add_argument(
            "--message",
            default="This is a test email sent via Django management command.",
            help="Email message body.",
        )

    def handle(self, *args, **options):
        recipient = options["recipient"] or settings.EMAIL_HOST_USER or settings.DEFAULT_FROM_EMAIL
        if not recipient:
            raise CommandError("No recipient specified. Use --to or set TEST_EMAIL_TO/EMAIL_HOST_USER.")

        subject = options["subject"]
        message = options["message"]
        from_email = options["sender"] or settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER
        backend = options["backend"] or settings.EMAIL_BACKEND
        timeout = options.get("timeout") or 10

        self.stdout.write(self.style.NOTICE("Preparing to send test email..."))
        self.stdout.write(f"Backend : {backend}")
        self.stdout.write(f"From    : {from_email}")
        self.stdout.write(f"To      : {recipient}")
        self.stdout.write(
            f"Host    : {settings.EMAIL_HOST}:{settings.EMAIL_PORT} TLS={settings.EMAIL_USE_TLS} SSL={settings.EMAIL_USE_SSL}"
        )

        if not settings.EMAIL_USE_SSL and not settings.EMAIL_USE_TLS:
            self.stdout.write(self.style.WARNING("TLS/SSL 均未启用，注意确认是否为可信网络环境。"))

        try:
            # 显式指定连接参数，方便暴露认证/连通性问题；使用上下文管理确保连接关闭
            with get_connection(
                backend=backend,
                host=settings.EMAIL_HOST,
                port=settings.EMAIL_PORT,
                username=settings.EMAIL_HOST_USER,
                password=settings.EMAIL_HOST_PASSWORD,
                use_tls=settings.EMAIL_USE_TLS,
                use_ssl=settings.EMAIL_USE_SSL,
                timeout=timeout,
            ) as conn:
                sent = send_mail(
                    subject=subject,
                    message=message,
                    from_email=from_email,
                    recipient_list=[recipient],
                    fail_silently=False,
                    connection=conn,
                )
        except Exception as exc:
            hint = ""
            msg = str(exc).lower()
            if "authentication" in msg or "535" in msg:
                hint = "（认证失败，请检查账号/授权码/发件人地址是否匹配）"
            elif "timed out" in msg:
                hint = f"（连接超时，当前超时 {timeout}s，可调整 --timeout 或检查网络/端口）"
            elif "name or service not known" in msg or "getaddrinfo" in msg:
                hint = "（DNS 解析失败，请检查 EMAIL_HOST 配置或网络）"
            raise CommandError(f"Failed to send test email: {exc} {hint}".strip()) from exc

        if sent:
            self.stdout.write(self.style.SUCCESS(f"Test email sent successfully to {recipient} (count={sent})"))
        else:
            raise CommandError("send_mail returned 0; email not sent.")
