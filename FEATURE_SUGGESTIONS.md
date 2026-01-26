# 功能增强建议 / Feature Suggestions

基于对现有代码库的分析，以下是针对系统功能增强的建议。

## 1. 全局搜索 (Global Search)
**现状**：目前的搜索分散在各个列表页（项目、任务、模板），无法跨模块查找。
**建议**：
- 在顶部导航栏添加全局搜索框。
- 支持同时搜索项目名称、任务标题、日报内容、文档附件。
- **技术实现**：
    - 使用 Django Q 对象组合查询（简单版）。
    - 或引入 `django-watson` / Elasticsearch（进阶版）。

## 2. 黑暗模式 (Dark Mode)
**现状**：系统 UI 似乎仅支持浅色模式。
**建议**：
- 支持跟随系统或手动切换深色模式，提升夜间开发体验。
- **技术实现**：
    - 使用 CSS Variables 定义颜色主题。
    - 添加 Theme Toggle 开关，将偏好存储在 `UserPreference` 模型中。

## 3. API 令牌与集成 (API Tokens & Integrations)
**现状**：系统主要依赖 Session 登录，缺乏对外的机器接口。
**建议**：
- 允许用户生成 Personal Access Tokens (PAT)。
- 支持 CI/CD 流水线（如 Jenkins/GitLab CI）自动调用 API 汇报构建状态或部署进度。
- **技术实现**：
    - 引入 `djangorestframework` 的 TokenAuthentication。
    - 创建 `APIToken` 模型管理令牌生命周期。

## 4. 移动端 PWA 支持 (Progressive Web App)
**现状**：Web 端响应式布局已具备，但移动端体验可进一步提升。
**建议**：
- 将网站升级为 PWA，支持“添加到主屏幕”。
- 支持离线查看缓存的日报或任务。
- **技术实现**：
    - 添加 `manifest.json` 和 `service-worker.js`。

## 5. 富文本/Markdown 编辑器升级
**现状**：日报和任务描述使用普通文本框或简单的 Markdown。
**建议**：
- 引入更强大的编辑器（如 Toast UI Editor 或 Tiptap）。
- 支持直接粘贴图片上传（目前需手动上传附件）。
- 支持 `@` 提及用户时的自动补全下拉框。

## 6. 自动化周报 (Automated Weekly Reports)
**现状**：只有日报。
**建议**：
- 每周五自动汇总本周的日报内容，生成周报草稿。
- 允许用户编辑后发送。
- **技术实现**：
    - 定时任务 (`cron`) 扫描本周日报。
    - 聚合 `today_work` 字段。
