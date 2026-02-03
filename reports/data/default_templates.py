
"""
Standard Daily Report Templates Definition.
Defines structure and default content for each role.
"""

DAILY_REPORT_TEMPLATES = {
    'mgr': {
        'name': 'Project Manager Daily / 项目经理日报',
        'role': 'mgr',
        'hint': '关注项目整体进度、风险控制、资源协调及里程碑管理。',
        'placeholders': {
            'mgr_progress': '本周里程碑达成情况 / Milestone Status',
            'mgr_risks': '风险预警与资源瓶颈 / Risks & Bottlenecks',
            'mgr_tomorrow': '明日重点推进事项 / Key Focus for Tomorrow'
        },
        'sample_md': """### 📅 今日重点 (Highlights)
- [ ] 主持了项目A的周会，确认了里程碑 M1 的延期风险
- [ ] 协调了设计资源支持项目B的紧急需求

### 📊 项目进度 (Project Status)
| 项目 | 阶段 | 进度 | 状态 | 备注 |
|---|---|---|---|---|
| **CRM系统** | 开发 | 60% | 🟢 正常 | 后端接口已完成 |
| **商城App** | 测试 | 85% | 🟡 风险 | 发现严重Bug阻塞 |

### 🚩 风险与问题 (Risks & Issues)
- **[High]** 服务器资源申请流程卡滞，需CTO审批
- **[Medium]** 第三方支付接口文档变更，需重新评估工时

### 📝 明日计划 (Plan)
- 跟进服务器资源申请
- 组织商城App上线前验收评审"""
    },
    'pm': {
        'name': 'Product Manager Daily / 产品经理日报',
        'role': 'pm',
        'hint': '关注需求分析、产品规划、用户反馈及数据分析。',
        'placeholders': {
            'product_today': '需求文档撰写与评审 / PRD & Review',
            'product_coordination': '跨部门沟通与决策 / Coordination',
            'product_tomorrow': '明日规划与跟进 / Plan'
        },
        'sample_md': """### 💡 需求与规划 (Requirements)
- **[PRD]** 完成了《会员积分体系 v2.0》需求文档初稿
- **[Roadmap]** 更新了 Q3 产品规划路线图

### 🗣️ 用户反馈 (Feedback)
- 收集到 5 条关于“搜索功能”的改进建议
- 客服反馈：用户无法找到“订单导出”按钮 (需优化交互)

### 📈 数据洞察 (Data Analysis)
- 昨日 DAU: 15,000 (+5%)
- 新功能“一键下单”转化率: 12% (未达预期 15%)

### 📅 明日计划 (Plan)
- 评审《会员积分体系 v2.0》需求
- 分析“一键下单”漏斗流失原因"""
    },
    'dev': {
        'name': 'Developer Daily / 开发工程师日报',
        'role': 'dev',
        'hint': '详细记录代码产出、技术难点、Blocker及解决方案。',
        'placeholders': {
            'today_work': '已完成功能与代码提交 / Completed Features & Commits',
            'progress_issues': '遇到的技术难点与阻塞 / Tech Issues & Blockers',
            'tomorrow_plan': '明日开发目标 / Dev Goals'
        },
        'sample_md': """### 💻 今日开发 (Coding)
- **[Feat]** 完成了用户登录接口 (API-101)
- **[Fix]** 修复了Token过期导致的闪退问题 (Bug-203)
- **[Refactor]** 优化了订单查询SQL性能 (Response: 500ms -> 50ms)

### 🚧 遇到的问题 (Blockers)
- 支付网关测试环境不稳定，影响联调 (已报障)
- 缺少部分UI切图 (已沟通 UI 补充)

### 📅 明日计划 (Plan)
- 完成支付回调逻辑开发
- 编写单元测试 (覆盖率目标 80%)"""
    },
    'qa': {
        'name': 'QA Engineer Daily / 测试工程师日报',
        'role': 'qa',
        'hint': '重点关注测试执行情况、缺陷统计及质量风险。',
        'placeholders': {
            'testing_scope': '今日测试范围与用例 / Testing Scope',
            'testing_progress': '执行进度与通过率 / Progress & Pass Rate',
            'bug_summary': '新增与待解决缺陷 / Bug Summary',
            'testing_tomorrow': '明日测试计划 / Plan'
        },
        'sample_md': """### 🧪 测试执行 (Execution)
- **覆盖模块**: 用户中心, 订单流, 支付网关
- **进度**: 用例执行 50/60 (83%)
- **结果**: 48 Pass, 2 Fail

### 🐛 缺陷汇总 (Bugs)
- **[Critical]** 无法使用微信支付 (ID: 501) - 阻塞
- **[Major]** 订单详情页样式错乱 (ID: 502) - 待修复

### 📉 质量风险 (Risks)
- iOS 16 兼容性测试尚未开始
- 性能测试 TPS 未达标 (< 500)

### 📅 明日计划 (Plan)
- 验证已修复的 Critical 缺陷
- 开始 iOS 16 兼容性测试"""
    },
    'ops': {
        'name': 'DevOps Daily / 运维工程师日报',
        'role': 'ops',
        'hint': '关注系统稳定性、监控告警、资源使用及变更管理。',
        'placeholders': {
            'ops_today': '运维操作与变更 / Ops Tasks',
            'ops_monitoring': '监控告警与故障处理 / Monitoring & Incidents',
            'ops_tomorrow': '明日维护计划 / Maintenance Plan'
        },
        'sample_md': """### 🖥️ 系统状态 (System Status)
- **CPU/Mem**: 正常 (Avg < 60%)
- **Uptime**: 99.99% (无宕机)
- **QPS**: Peak 2000 / Avg 500

### 🛠️ 维护操作 (Maintenance)
- 升级了 Nginx 到 1.24 版本 (无中断)
- 扩容了 Redis 集群节点 (Node-05)

### 🚨 告警处理 (Incidents)
- [已解决] 14:00 DB连接数突增报警 (原因: 慢查询，已Kill)

### 📅 明日计划 (Plan)
- 执行数据库备份恢复演练
- 更新生产环境 SSL 证书"""
    },
    'ui': {
        'name': 'Designer Daily / 设计师日报',
        'role': 'ui',
        'hint': '记录设计产出、交互优化及视觉验收情况。',
        'placeholders': {
            'ui_today': '设计稿产出 / Design Output',
            'ui_feedback': '反馈修改与验收 / Feedback & Review',
            'ui_tomorrow': '明日设计任务 / Design Tasks'
        },
        'sample_md': """### 🎨 今日设计 (Design)
- 完成了「个人中心」高保真设计图 (3P)
- 输出了「支付弹窗」交互规范

### 👁️ 视觉验收 (Review)
- 验收了 Android v2.1 版本，发现 3 处还原度问题 (已提交 Jira)
- 提供了 Loading 动画的 Lottie 文件

### 📅 明日计划 (Plan)
- 启动「活动页」头图设计
- 整理设计组件库 (Button, Input)"""
    }
}

TASK_TEMPLATES = [
    {
        'name': 'Feature Development / 功能开发',
        'title': '[Feat] ',
        'content': """## 📋 需求描述 (Description)
- **用户故事**: As a [User], I want to [Action], so that [Benefit].
- **关联文档**: [PRD链接] | [UI设计图]

## ✅ 验收标准 (Acceptance Criteria)
1. 用户可以通过手机号注册
2. 密码必须包含字母和数字
3. 注册成功后自动跳转至首页

## 🛠️ 技术方案 (Technical Design)
- **API**: `POST /api/v1/register`
- **DB**: 新增 `users` 表字段
- **依赖**: 需等待短信服务开通

## 📅 任务拆解 (Subtasks)
- [ ] 数据库设计 (2h)
- [ ] 接口开发 (4h)
- [ ] 单元测试 (2h)
- [ ] 联调 (2h)"""
    },
    {
        'name': 'Bug Fix / 缺陷修复',
        'title': '[Bug] ',
        'content': """## 🐛 问题描述 (Issue Description)
- **现象**: 点击支付按钮无反应
- **环境**: iOS 16, App v2.1.0
- **复现概率**: 必现

## 👣 复现步骤 (Steps to Reproduce)
1. 登录 App
2. 进入商品详情页
3. 点击“立即购买”

## 🔍 原因分析 (Root Cause)
- 初步排查是前端点击事件未绑定
- 后端日志无异常

## 🛠️ 修复方案 (Fix Plan)
- 修复前端 EventListener
- 增加空状态保护"""
    },
    {
        'name': 'Code Refactor / 代码重构',
        'title': '[Refactor] ',
        'content': """## 🎯 重构目标 (Goal)
- 提高 `OrderService` 类的可读性
- 降低圈复杂度 (Cyclomatic Complexity < 10)

## 📦 涉及范围 (Scope)
- 文件: `services/order.py`
- 模块: `OrderValidator`, `PriceCalculator`

## 🧪 验证计划 (Verification)
- [ ] 现有单元测试全部通过
- [ ] 新增边界条件测试用例
- [ ] 进行性能压测 (对比重构前后耗时)"""
    },
    {
        'name': 'Performance Optimization / 性能优化',
        'title': '[Perf] ',
        'content': """## 🚀 优化目标 (Goal)
- 接口响应时间: 500ms -> 100ms
- QPS: 100 -> 500

## 📊 现状分析 (Analysis)
- 慢查询日志显示 SQL 执行耗时 300ms
- Redis 缓存未命中率高

## 🛠️ 优化方案 (Solution)
1. 为 `user_id` 字段添加索引
2. 引入二级缓存
3. 优化 N+1 查询问题

## 📉 验证结果 (Result)
- 优化后 P99 耗时: 
- 优化后 QPS: """
    }
]
