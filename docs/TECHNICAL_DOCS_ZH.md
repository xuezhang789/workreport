# 技术文档索引 / Technical Documentation Index

本文档汇总了系统的技术架构、模块详情及维护指南。

## 核心模块文档 (Module Documentation)

*   **[Core 基础模块](technical/core.md)**
    *   涵盖：认证、权限 (RBAC)、文件上传、系统通用工具。
    *   重点：安全策略与基础服务。

*   **[Projects 项目管理](technical/projects.md)**
    *   涵盖：项目生命周期、成员管理、阶段配置。
    *   重点：权限隔离与可见性规则。

*   **[Tasks 任务系统](technical/tasks.md)**
    *   涵盖：任务/缺陷流转、SLA 引擎、状态机。
    *   重点：业务逻辑与协作流程。

*   **[Reports & Audit 报表与审计](technical/reports.md)**
    *   涵盖：统计分析、通知中心、操作审计日志。
    *   重点：数据聚合与合规性记录。

## 系统维护指南

### 1. 部署环境
*   **Python**: 3.9+
*   **Django**: 4.2+
*   **Database**: PostgreSQL (推荐) / SQLite (开发)
*   **Cache/Queue**: Redis (用于 Celery 和 Channels)

### 2. 常见维护操作
*   **清理临时文件**: `python manage.py cleanup_uploads`
*   **生成测试数据**: `python manage.py generate_test_data`
*   **审计日志归档**: `python manage.py archive_audit_logs`

### 3. 安全注意事项
*   请定期检查 `requirements.txt` 依赖库的安全性更新。
*   生产环境务必设置 `DEBUG=False` 并配置强 `SECRET_KEY`。
*   文件上传目录需配置 Web 服务器（Nginx/Apache）禁止执行脚本。
