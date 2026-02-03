# 功能增强路线图 / Feature Roadmap

## 1. 用户体验优化 (User Experience)
- [ ] **全局搜索增强**: 引入 Elasticsearch 或 Whoosh，支持对任务内容、评论及日报的全文检索。
- [ ] **暗色模式 (Dark Mode)**: 基于 CSS 变量实现一键切换深色主题。
- [ ] **移动端适配**: 优化表格在移动端的显示（如卡片视图切换）。

## 2. 系统架构升级 (Architecture)
- [ ] **消息队列 (Celery)**: 替换当前的 Python Threading 方案，用于处理邮件发送、报表生成等耗时任务。
- [ ] **缓存层 (Redis)**: 对高频查询（如权限校验、SLA 计算）引入 Redis 缓存。
- [ ] **API 规范化**: 迁移至 Django REST Framework (DRF)，提供标准的 RESTful API。

## 3. 新功能模块 (New Features)
- [ ] **甘特图编辑**: 支持在甘特图上直接拖拽调整任务时间。
- [ ] **自动化规则**: 允许用户定义简单的触发器（如：任务完成时自动分配给 QA）。
- [ ] **工时审批流**: 增加工时填报的审批环节，支持多级审批。
