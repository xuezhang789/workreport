from django.db import models
from django.contrib.auth.models import User
from .models import Project

class ProjectRepository(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='repositories', verbose_name="项目")
    name = models.CharField(max_length=100, verbose_name="仓库名称")
    url = models.URLField(verbose_name="仓库地址")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ['created_at']
        verbose_name = "项目仓库"
        verbose_name_plural = "项目仓库"

    def __str__(self):
        return f"{self.name} - {self.project.name}"
