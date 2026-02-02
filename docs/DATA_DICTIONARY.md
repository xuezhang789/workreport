# 数据字典 (Data Dictionary)

## 1. 用户 (User / Profile)
| 字段名 | 类型 | 描述 | 关联 |
| :--- | :--- | :--- | :--- |
| username | Char | 用户名 (唯一) | |
| email | Email | 邮箱 | |
| profile.position | Char | 职位 | dev, qa, pm, ui, ops, mgr |

## 2. 项目 (Project)
| 字段名 | 类型 | 描述 | 关联 |
| :--- | :--- | :--- | :--- |
| name | Char | 项目名称 | |
| code | Char | 项目代号 (唯一) | |
| owner | FK | 项目负责人 | User |
| members | M2M | 项目成员 | User |
| current_phase | FK | 当前阶段 | ProjectPhaseConfig |
| overall_progress | Decimal | 总体进度 (%) | |

## 3. 任务 (Task)
| 字段名 | 类型 | 描述 | 关联 |
| :--- | :--- | :--- | :--- |
| title | Char | 任务标题 | |
| content | Text | 任务内容 | |
| project | FK | 所属项目 | Project |
| user | FK | 负责人 | User (必须是项目成员) |
| status | Char | 状态 | todo, in_progress, done, closed |
| priority | Char | 优先级 | high, medium, low |
| due_at | DateTime | 截止时间 | |

## 4. 日报 (DailyReport)
| 字段名 | 类型 | 描述 | 关联 |
| :--- | :--- | :--- | :--- |
| user | FK | 填报人 | User |
| date | Date | 日期 | |
| projects | M2M | 关联项目 | Project |
| today_work | Text | 今日工作内容 | |
| progress_issues | Text | 进度与问题 | |
| tomorrow_plan | Text | 明日计划 | |

---

# 数据生成工具说明

## 功能
`generate_large_scale_data` 是一个 Django Management Command，用于生成大规模测试数据。

## 用法
```bash
python3 manage.py generate_large_scale_data [options]
```

## 参数
- `--users`: 生成用户数量 (默认: 500)
- `--projects`: 生成项目数量 (默认: 10000)
- `--tasks`: 生成任务数量 (默认: 100000)
- `--reports`: 生成日报数量 (默认: 1000000)
- `--clear`: **慎用**。生成前清空现有数据 (包含项目、任务、日报等)。

## 示例
```bash
# 生成全量数据
python3 manage.py generate_large_scale_data

# 生成少量测试数据
python3 manage.py generate_large_scale_data --users 50 --projects 100 --tasks 500 --reports 1000
```
