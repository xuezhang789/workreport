from work_logs.models import RoleTemplate
import json

def generate_workbench_guidance(total, completed, overdue, in_progress, pending, streak, has_today_report, user_role, today_tasks_count, upcoming_tasks_count):
    """生成智能工作台引导文案"""
    completion_rate = (completed / total * 100) if total else 0
    
    guidance = {
        'primary': '',
        'secondary': '',
        'actions': [],
        'status': 'normal'
    }
    
    # 获取角色模板配置（如果有）
    role_tmpl = RoleTemplate.objects.filter(role=user_role, is_active=True).first()
    custom_hint = role_tmpl.hint if role_tmpl else None

    # 根据不同情况生成主要引导文案
    if not has_today_report:
        if custom_hint:
             guidance['primary'] = "📊 日报待填写 / Report Pending"
             guidance['secondary'] = custom_hint
        elif user_role == 'dev':
            guidance['primary'] = "📝 今日待提交 / Today's Report Pending"
            guidance['secondary'] = "记录今日开发进展，为团队协作提供透明度 / Log today's development progress for team transparency"
        elif user_role == 'qa':
            guidance['primary'] = "🧪 测试日报待填写 / QA Report Pending"
            guidance['secondary'] = "记录测试范围和发现的问题，确保产品质量 / Document testing scope and issues found for quality assurance"
        elif user_role == 'pm':
            guidance['primary'] = "📋 产品日报待提交 / Product Report Pending"
            guidance['secondary'] = "同步产品进展和协调事项，推动项目前进 / Sync product progress and coordination to drive projects forward"
        else:
            guidance['primary'] = "📊 工作日报待填写 / Work Report Pending"
            guidance['secondary'] = "分享今日工作成果，让团队了解你的贡献 / Share today's work achievements and let the team know your contributions"
        guidance['status'] = 'urgent'
        guidance['actions'].append({
            'text': '立即提交日报 / Submit Report',
            'url': 'reports:daily_report_create',
            'priority': 'high'
        })
    
    # 任务相关引导
    elif overdue > 0:
        guidance['primary'] = "⚠️ 有逾期任务需要处理 / Overdue Tasks Need Attention"
        guidance['secondary'] = f"您有 {overdue} 个任务已逾期，请及时处理以避免项目延期 / You have {overdue} overdue tasks, please handle them promptly to avoid project delays"
        guidance['status'] = 'warning'
        guidance['actions'].append({
            'text': '查看逾期任务 / View Overdue Tasks',
            'url': 'tasks:task_list',
            'priority': 'high'
        })
    
    elif today_tasks_count > 0:
        guidance['primary'] = "🎯 今日任务待完成 / Today's Tasks Pending"
        guidance['secondary'] = f"您有 {today_tasks_count} 个任务今日到期，专注完成这些任务 / You have {today_tasks_count} tasks due today, focus on completing these tasks"
        guidance['status'] = 'normal'
        guidance['actions'].append({
            'text': '查看今日任务 / View Today\'s Tasks',
            'url': 'tasks:task_list',
            'priority': 'medium'
        })
    
    elif upcoming_tasks_count > 0:
        guidance['primary'] = "📅 即将到期任务 / Upcoming Deadlines"
        guidance['secondary'] = f"您有 {upcoming_tasks_count} 个任务将在3天内到期，提前规划时间 / You have {upcoming_tasks_count} tasks due in 3 days, plan your time in advance"
        guidance['status'] = 'normal'
    
    elif in_progress > 0:
        guidance['primary'] = "🚀 任务进行中 / Tasks in Progress"
        guidance['secondary'] = f"您有 {in_progress} 个任务正在进行中，保持专注完成 / You have {in_progress} tasks in progress, stay focused to complete them"
        guidance['status'] = 'normal'
    
    elif total == 0:
        guidance['primary'] = "🌟 开始新任务 / Start New Tasks"
        guidance['secondary'] = "当前没有分配的任务，可以主动申请新任务或创建个人任务 / No tasks assigned currently, you can proactively apply for new tasks or create personal tasks"
        guidance['status'] = 'info'
        guidance['actions'].append({
            'text': '查看所有项目 / View All Projects',
            'url': 'projects:project_list',
            'priority': 'low'
        })
    
    # 连签激励
    if streak >= 7:
        guidance['secondary'] += f" 🔥 连续提交日报 {streak} 天，继续保持！/ {streak} days streak, keep it up!"
    elif streak >= 3:
        guidance['secondary'] += f" 📈 连续提交日报 {streak} 天，很棒的坚持！/ {streak} days streak, great consistency!"
    
    # 完成率激励
    if total > 0 and completion_rate >= 80:
        guidance['secondary'] += f" ✅ 任务完成率 {completion_rate:.1f}%，表现优秀！/ Task completion rate {completion_rate:.1f}%, excellent performance!"
    
    return guidance
