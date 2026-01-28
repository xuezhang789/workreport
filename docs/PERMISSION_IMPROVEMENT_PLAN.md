# 权限设计方案评估与改进计划

## 1. 现状评估

### 1.1 优点
- **分层明确**: 区分了超级管理员、项目经理、普通成员。
- **工具封装**: `reports/utils.py` 提供了 `get_accessible_projects` 等便捷函数。
- **细粒度控制**: 任务协作人只能修改状态，无法修改其他字段。

### 1.2 风险与不足
- **逻辑分散**: 权限检查散落在各个 View 函数的开头，容易遗漏。
- **硬编码**: 角色名称（如 `'mgr'`, `'pm'`）硬编码在代码中，若需修改角色定义涉及面广。
- **缺乏统一入口**: API 接口与模板视图的权限处理方式不完全一致。

## 2. 改进方案

### 2.1 引入统一权限类 (Permission Classes)
参考 DRF 的权限设计，为 Django Views 设计类似的权限类。

```python
# core/permissions.py

class BasePermission:
    def has_permission(self, request, view):
        return True
    
    def has_object_permission(self, request, view, obj):
        return True

class IsProjectManager(BasePermission):
    def has_object_permission(self, request, view, project):
        return project.members.filter(user=request.user, role='manager').exists()
```

### 2.2 视图层重构 (Mixin 模式)
使用 Mixin 替代函数内部的 `if` 判断。

```python
class ProjectAccessMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_superuser:
            return qs
        return qs.filter(project__in=get_accessible_projects(self.request.user))
```

### 2.3 角色常量化
将所有角色定义移至 `core.constants`。

```python
class UserRole(models.TextChoices):
    MANAGER = 'mgr', '项目管理'
    DEV = 'dev', '开发'
    # ...
```

## 3. 实施路线图

1.  **第一阶段 (清理)**: 扫描所有视图，确保 `get_accessible_projects` 被正确调用。
2.  **第二阶段 (重构)**: 提取 `ProjectAccessMixin` 并应用到 `TaskListView`, `DailyReportListView`。
3.  **第三阶段 (增强)**: 引入 `django-guardian` 或自定义中间件，实现对象级权限的统一管理（如需更复杂场景）。

## 4. 安全审计建议
- 定期审查 `AuditLog`，关注 `failure` 状态的 `access` 或 `update` 操作，识别潜在的越权尝试。
- 对关键操作（如导出数据、批量删除）增加二次确认或更高的权限要求。
