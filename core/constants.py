from django.db import models

class TaskStatus(models.TextChoices):
    TODO = 'todo', '待处理 / To Do'
    IN_PROGRESS = 'in_progress', '进行中 / In Progress'
    BLOCKED = 'blocked', '阻塞中 / Blocked'
    IN_REVIEW = 'in_review', '待评审 / In Review'
    DONE = 'done', '已完成 / Done'
    CLOSED = 'closed', '已关闭 / Closed'
