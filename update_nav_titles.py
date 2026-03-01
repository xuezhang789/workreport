import os
import re

replacements = [
    {
        "file": "templates/reports/workbench.html",
        "pattern": r'nav_title="工作台 / Workbench" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="工作台" nav_subtitle="Workbench"'
    },
    {
        "file": "templates/reports/project_list.html",
        "pattern": r'nav_title="项目列表 / Projects" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="项目列表" nav_subtitle="Projects"'
    },
    {
        "file": "templates/reports/my_reports.html",
        "pattern": r'nav_title="我的日报 / My Reports" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="我的日报" nav_subtitle="My Reports"'
    },
    {
        "file": "templates/reports/daily_report_form.html",
        "pattern": r'nav_title="团队在线日报 / Daily Report" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="团队在线日报" nav_subtitle="Daily Report"'
    },
    {
        "file": "templates/registration/account_settings.html",
        "pattern": r'nav_title="个人中心 / Personal Center" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="个人中心" nav_subtitle="Personal Center"'
    },
    {
        "file": "templates/reports/global_search.html",
        "pattern": r'nav_title="全局搜索 / Global Search" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="全局搜索" nav_subtitle="Global Search"'
    },
    {
        "file": "templates/reports/stats.html",
        "pattern": r'nav_title="统计分析 / Statistics" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="统计分析" nav_subtitle="Statistics"'
    },
    {
        "file": "templates/reports/audit_logs.html",
        "pattern": r'nav_title="审计日志 / Audit Logs" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="审计日志" nav_subtitle="Audit Logs"'
    },
    {
        "file": "templates/reports/admin_reports.html",
        "pattern": r'nav_title="管理员日报 / Admin Reports" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="管理员日报" nav_subtitle="Admin Reports"'
    },
    {
        "file": "templates/reports/teams.html",
        "pattern": r'nav_title="团队管理 / Team Management" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="团队管理" nav_subtitle="Team Management"'
    },
    {
        "file": "templates/reports/template_center.html",
        "pattern": r'nav_title="模板中心 / Template Center" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="模板中心" nav_subtitle="Template Center"'
    },
    {
        "file": "templates/reports/role_template_manage.html",
        "pattern": r'nav_title="角色模板管理 / Role Templates" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="角色模板管理" nav_subtitle="Role Templates"'
    },
    {
        "file": "templates/reports/performance_board.html",
        "pattern": r'nav_title="绩效与统计看板 / Performance & Stats" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="绩效看板" nav_subtitle="Performance Board"'
    },
    {
        "file": "templates/reports/project_detail.html",
        "pattern": r'nav_title="项目详情 / Project Detail" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="项目详情" nav_subtitle="Project Detail"'
    },
    {
        "file": "templates/reports/personnel_list.html",
        "pattern": r'nav_title="人事管理 / Personnel Management" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="人事管理" nav_subtitle="Personnel Management"'
    },
    {
        "file": "templates/reports/notification_list.html",
        "pattern": r'nav_title="通知中心 / Notification Center" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="通知中心" nav_subtitle="Notification Center"'
    },
    {
        "file": "templates/core/invitation_list.html",
        "pattern": r'nav_title="邀请管理 / Invitations" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="邀请管理" nav_subtitle="Invitations"'
    },
    {
        "file": "templates/403.html",
        "pattern": r'nav_title="无权限 / Access Denied" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="无权限" nav_subtitle="Access Denied"'
    },
    {
        "file": "templates/reports/report_detail.html",
        "pattern": r'nav_title="日报详情 / Report Detail" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="日报详情" nav_subtitle="Report Detail"'
    },
    {
        "file": "templates/reports/project_form.html",
        "pattern": r'nav_title="项目管理 / Project" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="项目管理" nav_subtitle="Project Management"'
    },
    {
        "file": "templates/reports/project_stage_change.html",
        "pattern": r'nav_title="变更项目阶段 / Change Project Stage" nav_subtitle="[^"]+"',
        "replacement": 'nav_title="变更项目阶段" nav_subtitle="Change Project Stage"'
    },
    {
        "file": "templates/reports/project_history.html",
        "pattern": r'nav_title="变更历史 / History" nav_subtitle=project\.name',
        "replacement": 'nav_title="变更历史" nav_subtitle="Change History"'
    },
    {
        "file": "templates/reports/project_stage_history.html",
        "pattern": r'nav_title="变更历史 / History" nav_subtitle=project\.name',
        "replacement": 'nav_title="变更历史" nav_subtitle="Change History"'
    },
    {
        "file": "templates/reports/project_confirm_delete.html",
        "pattern": r'nav_title="删除项目 / Delete Project" nav_subtitle=project\.name\|add:" / Project"',
        "replacement": 'nav_title="删除项目" nav_subtitle="Delete Project"'
    }
]

base_dir = "/Users/lingchong/Downloads/wwwroot/workreport"

for item in replacements:
    file_path = os.path.join(base_dir, item["file"])
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        new_content = re.sub(item["pattern"], item["replacement"], content)
        
        if content != new_content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Updated {item['file']}")
        else:
            print(f"No match found for {item['file']}")
    else:
        print(f"File not found: {item['file']}")
