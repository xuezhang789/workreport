# TM 团队日报与任务平台使用教程 / TM Team Daily & Task Platform Usage Guide

## 目录 / Contents
1. 快速开始 / Quick Start
2. 账户与安全 / Accounts & Security
3. 日报 / Daily Reports
4. 任务 / Tasks
5. 项目 / Projects
6. 模板中心 / Template Center
7. 统计与绩效 / Stats & Performance
8. 审计日志 / Audit Logs
9. 常见问题 / FAQ

---

## 1. 快速开始 / Quick Start
1) 登录 / Login：访问 `/accounts/login/`，注册请去 `/accounts/register/`。  
2) 进入工作台 / Go to Workbench：`/reports/workbench/` 查看任务与日报提示。  
3) 填写日报 / Create report：`/reports/new/` 选择角色、日期、项目（可多选），填写并提交。  
4) 查看任务 / View tasks：`/reports/tasks/`，筛选状态/项目/关键词，完成后批量或单条“已完成”。  
5) 管理入口 / Admin access：需管理员或项目管理员权限，导航“管理入口 / Admin”进入任务/日报/统计等页面。  

---

## 2. 账户与安全 / Accounts & Security
- 个人中心 `/accounts/settings/`：修改用户名、密码（含强度校验）、邮箱绑定（验证码冷却，生产不回显验证码）。  
- 权限 / Permissions：管理员 is_staff；项目管理员在项目管理中配置。无权限会显示友好 403 页面。  
- 登出 / Logout：导航“退出登录 / Logout”。  

---

## 3. 日报 / Daily Reports
- 填写 / Create：`/reports/new/`，角色自适配字段；可多选项目。  
- 模板套用 / Apply Template：输入模板名后点“套用模板 / Apply Template”，按 项目→角色→全局 回退，未命中会提示清空筛选或用全局。  
- 我的日报 / My Reports：`/reports/my/`，按日期/状态/项目/角色/关键词筛选；导出 CSV（超限提示请缩小过滤）。  
- 管理员日报 / Admin Reports：`/reports/admin/reports/`，筛选全员日报并导出，需权限。  
- 缺报统计 / Missing: 统计页 `/reports/stats/` 有缺报列表，可一键催报。  

---

## 4. 任务 / Tasks
- 我的任务 / My Tasks：`/reports/tasks/`  
  - 筛选：状态/项目/关键词/紧急（hot）。  
  - 批量：选择后“批量完成/重新打开/导出选中”。  
  - SLA 提示：显示当前红/黄阈值，任务卡标记剩余或逾期。  
  - 导出：按钮旁有“数据过大请缩小过滤”提示。  
- 管理任务 / Admin Tasks：`/reports/tasks/admin/`  
  - 创建：`/reports/tasks/admin/new/` 指派用户、项目、状态、截止时间。  
  - 批量：完成/重开/逾期，操作后自动刷新缓存。  
  - 导出/统计：管理员任务列表/统计页支持导出，超过限额需缩小筛选。  

---

## 5. 项目 / Projects
- 列表 `/reports/projects/`：筛选、查看成员/管理员。  
- 创建/编辑/删除（软禁用）：`/reports/projects/new/` 和编辑页；保存后缓存自动刷新。  
- 导出：需先设置过滤条件。  

---

## 6. 模板中心 / Template Center
- 入口 `/reports/templates/center/`。  
- 创建：日报/任务模板，支持项目/角色维度，自动版本号。  
- 筛选与排序：关键词、角色、项目，排序方式（按版本/按更新时间），分页与跳页。  
- 套用优先级 / Apply priority：项目 → 角色 → 全局，回退时返回 `fallback` 提示。  

---

## 7. 统计与绩效 / Stats & Performance
- 统计 `/reports/stats/`：缺报列表、项目 SLA 达成、逾期 Top；显示当前 SLA 阈值与“上次刷新时间”，缓存约 10 分钟，可点击“刷新数据”。导出前提示缩小过滤。  
- 绩效 `/reports/performance/`：项目/角色完成率、逾期率、连签趋势；显示 SLA 阈值、缓存提示、刷新按钮，支持导出（项目/角色/连签）与周报邮件。  

---

## 8. 审计日志 / Audit Logs
- 入口 `/reports/audit/`：按日期、动作、方法、用户、路径筛选，支持导出；无权限显示友好 403。  

---

## 9. 常见问题 / FAQ
- **导出失败/超限 / Export too large**：系统限额 5000 行，提示时请缩小筛选条件。  
- **模板未命中 / Template not found**：清空模板名或项目筛选，使用角色或全局模板回退。  
- **缓存未更新 / Cache stale**：性能/统计缓存约 10 分钟，可点击“刷新数据”；数据变更后可稍等或刷新。  
- **权限不足 / No permission**：联系管理员或项目管理员授予权限，或使用管理员账号访问。  

如需更详细的操作截图或流程说明，可在 README / PROJECT_GUIDE 基础上补充。 / If you need more screenshots or flow details, extend README/PROJECT_GUIDE accordingly.
