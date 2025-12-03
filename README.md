# TM 团队日报与任务平台 / Team Daily Report & Task Platform

支持团队日报、任务、项目、模板、SLA、统计/绩效看板的综合协作平台。本文档涵盖功能模块、使用指南、部署流程与配置说明。

## 功能模块 / Modules
- **认证与账户 / Auth & Account**
  - 注册、登录、退出；用户名唯一性与密码强度校验。
  - 个人中心：用户名/密码/邮箱绑定；验证码冷却与提示。
- **日报 / Daily Reports**
  - 填写、编辑、查看我的日报；角色/日期/项目/状态筛选与导出。
  - 连签统计与缺报提醒（催报邮件）。
- **任务 / Tasks**
  - 我的任务与管理员任务列表：筛选（状态/项目/关键词）、逾期/紧急标记、批量操作与导出。
  - SLA 计时：暂停/恢复、红/黄阈值配置与提醒，列表/看板显示当前阈值。
- **项目 / Projects**
  - 创建、编辑、删除项目；成员/管理员分配；项目级 SLA 小时。
- **模板中心 / Template Center**
  - 日报/任务模板的创建、版本记录、关键词/角色/项目筛选、分页与使用次数排序。
  - 模板套用：项目→角色→全局优先级，智能推荐（按项目/角色与 usage_count），支持替换/追加。
- **统计与绩效 / Stats & Performance**
  - 统计看板：日报缺报、项目 SLA、角色/项目汇总；SLA 预警过滤。
  - 绩效看板：项目/角色完成率、逾期率、连签；周报发送；SLA 预警过滤。
  - 缓存约 10 分钟，可在性能/统计页刷新查看“上次刷新时间”。
- **导出队列 / Export Queue**
  - 超过阈值的导出可加 `queue=1` 入队，后台生成 CSV；状态/下载接口提供轮询。
- **偏好设置 / Preferences**
  - 工作台、绩效看板卡片显示偏好可同步到服务端（UserPreference），跨设备一致。
- **审计 / Audit**
  - 导出、删除、访问等操作记录列表与导出。

## 使用方法 / Usage Guide
### 日报
1. 进入 `我的工作台 / Workbench`，点击“填写日报 / New Report”。
2. 可选择智能推荐模板或输入模板名，支持替换/追加；项目多选按优先级回退。
3. 填写后提交，查看“我的日报 / My Reports”筛选或导出 CSV。

### 任务
1. “我的任务 / My Tasks”中按状态/项目/关键词筛选；开启“hot”查看 SLA 预警任务。
2. 导出：小数据直接下载，大数据使用 `queue=1` 参数排队，返回 `job_id` 后调用  
   `export/jobs/<id>/` 轮询状态，完成后用 `export/jobs/<id>/download/` 下载。
3. 管理端在“任务管理 / Tasks Admin”创建/分配，支持批量操作与导出。

### 模板中心
1. 访问“模板中心 / Template Center”，按关键词/角色/项目/排序（版本/更新时间/使用次数）筛选。
2. 创建日报/任务模板后自动版本化，列表显示使用次数，智能推荐接口按项目/角色返回常用模板。

### 统计与绩效
- “绩效看板 / Performance Board”：查看完成率、逾期率、连签，刷新缓存，发送周报，SLA 预警过滤。
- “统计看板 / Stats”：查看缺报、项目 SLA、角色/项目汇总，支持 SLA 预警过滤与导出。

## 部署流程 / Deployment
1. **环境要求**：Python 3.10+，可选 Redis/Memcached（未来扩展缓存/限流）。
2. **依赖安装**：
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **数据库迁移**：
   ```bash
   python manage.py migrate
   ```
4. **创建管理员**：
   ```bash
   python manage.py createsuperuser
   ```
5. **启动开发服务器**：
   ```bash
   python manage.py runserver
   ```
6. **生产部署要点**：关闭 DEBUG，设置 SECRET_KEY/ALLOWED_HOSTS，使用 gunicorn/uwsgi + Nginx，执行 `collectstatic` 提供静态资源。

## 配置说明 / Configuration
- `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS`：安全基础配置。
- 邮件：`EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_SSL/TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`，用于验证码/通知。
- SLA：`SLA_REMIND_HOURS`（全局小时），`SystemSetting` 中的 `sla_thresholds`（红/黄阈值）可通过 SLA 配置页更新。
- 导出阈值：`MAX_EXPORT_ROWS`（views.py 顶部），超限时可用 `queue=1` 入队。
- 缓存：性能/统计看板缓存约 10 分钟；信号在任务/日报保存、删除、项目/模板变更时会清理。
- 偏好：`UserPreference` 存储卡片显示等 JSON 数据，API `prefs/`、`prefs/save/`。

## 常见问题 / FAQ
- **导出提示数据过大**：使用过滤条件或在 URL 加 `queue=1` 入队，然后轮询 `export/jobs/<id>/` 查看状态，完成后下载。
- **SLA 提醒**：确保项目设置 SLA 小时，并在 SLA 配置页设置红/黄阈值；任务列表/看板会显示当前阈值和预警。
- **模板未命中**：确认项目/角色筛选，模板套用按“项目→角色→全局”回退，并有 fallback 提示；可查看“使用次数”排序选择常用模板。
- **缓存未更新**：性能/统计看板默认缓存约 10 分钟，可点击页面刷新；数据变更（任务/日报/项目/模板更新）会触发缓存失效。
- **偏好未同步**：登录后卡片显示偏好会保存到服务端；如遇失败会回退到本地存储。
