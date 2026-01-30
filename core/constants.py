from django.db import models

class TaskCategory(models.TextChoices):
    TASK = 'TASK', '任务-TASK'
    BUG = 'BUG', '缺陷-BUG'

class TaskStatus(models.TextChoices):
    TODO = 'todo', '待处理 / To Do'
    IN_PROGRESS = 'in_progress', '进行中 / In Progress'
    BLOCKED = 'blocked', '阻塞中 / Blocked'
    IN_REVIEW = 'in_review', '待评审 / In Review'
    DONE = 'done', '已完成 / Done'
    CLOSED = 'closed', '已关闭 / Closed'
    
    # Bug specific statuses
    NEW = 'new', '新建 / New'
    CONFIRMED = 'confirmed', '已确认缺陷 / Confirmed'
    FIXING = 'fixing', '修复中 / In Progress'
    VERIFYING = 'verifying', '验证中 / Verifying'
