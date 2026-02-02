# This file has been refactored and split into multiple files.
# New files:
# - reports/daily_report_views.py
# - reports/statistics_views.py
# - reports/export_views.py
# - reports/template_views.py
# - reports/audit_views.py
# - reports/search_views.py

from .daily_report_views import *
from .statistics_views import *
from .export_views import *
from .template_views import *
from .audit_views import *
from .search_views import *
from .notification_views import *

# Explicitly export internal services used by tests
# 显式导出测试使用的内部服务
from reports.services.stats import get_performance_stats as _performance_stats
