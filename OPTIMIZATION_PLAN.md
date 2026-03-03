# 综合代码优化与重构计划

## 1. 执行摘要
本文档概述了 `workreport` 代码库现代化的战略计划，旨在解决在全面审计中发现的技术债务、性能瓶颈和安全风险。目标是提高可维护性，减少服务器响应时间，并加固系统以抵御常见漏洞。

## 2. 架构重构

### 2.1 `tasks/views.py` 的模块化
**当前状态**: `tasks/views.py` 是一个单体模块（>2000行），包含混合关注点：管理视图、标准用户视图、API 端点和实用逻辑。
**策略**: 拆分为 `tasks/views/` 包：
- `__init__.py`: 暴露通用视图以保持兼容性。
- `admin_views.py`: `admin_task_list`, `admin_task_edit` 等。
- `user_views.py`: `task_list`, `task_detail`, `task_create`。
- `api_views.py`: `task_search_api`, `task_stats_api`。
- `utils.py`: 任务视图特定的辅助函数。

### 2.2 服务层提取
**当前状态**: 业务逻辑（例如 SLA 计算、通知触发）与视图逻辑耦合。
**策略**:
- 确保所有 SLA 逻辑严格位于 `tasks/services/sla.py` 中。
- 将通知编排移动到 `reports/services/notification_service.py`。

## 3. 性能优化

### 3.1 N+1 查询解决
**识别出的热点**:
- **`admin_task_list`**: 如果没有正确预取，SLA 计算循环会触发相关字段的延迟加载。
- **`project_list`**: 分页循环内的权限检查 (`get_manageable_projects`) 可能非常昂贵。
- **`_send_phase_change_notification`**: 循环遍历经理/管理员以收集电子邮件。

**修复措施**:
- 在 `admin_task_list` 中积极使用 `select_related` 和 `prefetch_related`。
- 每个请求批量获取一次权限数据（例如，“用户 X 管理项目 A, B, C”），而不是每行检查。
- 缓存 `SystemSetting` 值（SLA 配置），以避免循环中的重复数据库命中。

### 3.2 数据库索引
- 审查 `Task` 过滤字段：`status`, `priority`, `assigned_to`, `project`。
- 确保经常排序/过滤的列（例如 `created_at`, `due_at`）存在索引。

## 4. 安全加固

### 4.1 XSS 防护
**发现**: `templates/registration/account_settings.html` 使用 `innerHTML` 在 JavaScript 中渲染用户控制的数据（头像 URL）。
**修复**:
- 将 `element.innerHTML = '<img src="' + url + '...">'` 替换为 `element.src = url` 或 `element.textContent`。
- 审计所有 `|safe` 模板过滤器的使用。

### 4.2 错误处理与日志记录
**发现**: `core/utils.py` 和 `audit_service.py` 中的宽泛 `except Exception:` 块掩盖了特定错误，使调试变得困难，并可能隐藏关键故障。
**修复**:
- 捕获特定异常（例如 `ValueError`, `IOError`）。
- 确保所有捕获的异常都记录了堆栈跟踪 (`logger.error(..., exc_info=True)`)。

### 4.3 输入验证
- 增强 `_validate_file` 以确保除扩展名之外的严格 MIME 类型检查。
- 在 `project_search_api` 中清理输入以防止潜在注入（尽管 ORM 处理 SQLi，但逻辑错误仍可能发生）。

## 5. 实施路线图

### 第一阶段：准备与安全 (第1天)
- [x] 创建详细的实施任务。
- [x] 修复 `account_settings.html` 中的关键 XSS。
- [x] 加强 `core/utils.py` 和 `audit_service.py` 中的异常处理。

### 第二阶段：重构 (第2-3天)
- [x] 将 `tasks/views.py` 拆分为模块。
- [x] 验证 URL 路由无回归。
- [x] 从 `admin_task_list` 中提取复杂逻辑到服务层。

### 第三阶段：性能 (第4天)
- [x] 优化 `admin_task_list` 查询（修复 N+1）。
- [x] 实现 `SystemSetting` 的缓存。
- [x] 优化 `project_list` 权限逻辑。

### 第四阶段：验证与交付 (第5天)
- [x] 运行完整的测试套件。
- [x] 对优化后的端点执行负载测试。
- [x] 生成最终的“系统优化报告”。
