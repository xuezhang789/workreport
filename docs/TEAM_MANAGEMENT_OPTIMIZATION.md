# 团队管理弹窗优化技术文档 / Team Management Modal Optimization Documentation

## 1. 概述 / Overview
本项目旨在优化团队管理页面的用户体验，实现无刷新（AJAX）操作和实时数据同步（WebSocket）。

## 2. 技术实现 / Technical Implementation

### 2.1 后端 API 改造 (Django Views)
文件: `reports/views_teams.py`

我们改造了以下视图以支持 AJAX 请求并返回 JSON 响应：
- `team_member_update_role`: 更新成员角色
- `team_member_add_project`: 添加项目
- `team_member_remove_project`: 移除项目

**响应格式:**
如果请求头包含 `X-Requested-With: XMLHttpRequest`，返回：
```json
{
    "status": "success",
    "message": "Operation successful",
    "data": { ... } // Updated data (e.g. project list)
}
```
否则，保留原有的重定向逻辑以兼容非 JS 环境。

### 2.2 实时同步 (Django Channels)
文件: `reports/consumers.py`, `reports/routing.py`

新增 `TeamUpdatesConsumer`，监听 `team_updates_global` 组。
当后端执行写操作成功后，通过 Channel Layer 广播消息：
```python
{
    "type": "team_update",
    "user_id": 123,
    "action": "update_role",
    "data": { ... },
    "sender_id": 456
}
```

### 2.3 前端重构 (Vanilla JS)
文件: `templates/reports/teams.html`

- **WebSocket**: 页面加载时连接 `/ws/team-updates/`，监听消息并更新 UI。
- **Fetch API**: 封装 `fetchWithRetry` 函数，支持网络异常重试（默认 3 次）。
- **DOM 更新**:
    - `updateRowRole`: 更新表格行的角色徽章。
    - `updateRowProjects`: 更新表格行的项目标签。
    - `renderModalProjects`: 如果弹窗开启，实时刷新弹窗内的项目列表。
- **交互优化**:
    - 提交时按钮显示 "Updating..." 并禁用。
    - 操作成功/失败显示 Toast 通知。
    - 冲突检测：如果收到来自其他管理员的更新消息，显示警告 Toast。

## 3. 性能与可靠性 / Performance & Reliability

- **API 响应**: 通过返回轻量级 JSON 替代 HTML 页面重载，响应时间显著降低 (<200ms typ.)。
- **重试机制**: 前端网络请求失败会自动重试，提高在不稳定网络下的成功率。
- **并发处理**: 通过 WebSocket 广播实现即时状态同步，减少数据不一致风险。

## 4. 测试 / Testing

已编写单元测试 `reports/tests/test_team_api.py` 覆盖所有 API 场景：
- 角色更新
- 项目添加
- 项目移除
- 权限验证
- JSON 响应结构验证

运行测试:
```bash
python manage.py test reports.tests.test_team_api
```
