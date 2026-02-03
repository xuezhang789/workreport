
# 日报模板系统使用说明 / Daily Report Template System Usage

## 1. 简介
本系统提供了一套基于 YAML 配置的日报模板生成工具，支持多角色、版本控制及自定义字段配置。

## 2. 目录结构
- **定义文件**: `reports/data/definitions/roles.yaml`
- **初始化脚本**: `core/management/commands/init_role_templates.py`
- **文档**: `docs/templates/`

## 3. 模板定义规范 (YAML)
请参考 `reports/data/definitions/roles.yaml` 进行配置。

### 核心字段
| 字段 | 类型 | 说明 |
|---|---|---|
| `role` | String | 角色代码 (dev, qa, pm, mgr, ops, ui) |
| `name` | String | 模板名称 |
| `hint` | String | 填写提示语 |
| `version` | Integer | 模板版本号 |
| `fields` | List | 字段定义列表 |
| `metrics` | List | 关键指标定义列表 |

### Field 属性
- `key`: 对应数据库模型字段名 (如 `today_work`)
- `label`: 前端显示标签
- `required`: 是否必填
- `type`: 字段类型 (markdown, text, number)
- `default`: 默认填充内容 (Markdown 格式)

### Metrics 属性
- `key`: 指标键名 (如 `commit_count`)
- `label`: 指标名称
- `type`: 数据类型 (integer, float)

## 4. 初始化与更新
使用 Django Management Command 进行初始化。该命令是幂等的，可重复执行。

```bash
# 初始化 (默认使用 prod 环境配置)
python manage.py init_role_templates

# 指定配置文件
python manage.py init_role_templates --config=reports/data/definitions/my_roles.yaml

# 指定环境 (日志打印用)
python manage.py init_role_templates --env=test
```

## 5. 开发指南
### 添加新角色
1. 在 `core.models.Profile.ROLE_CHOICES` 中添加新角色定义。
2. 在 `roles.yaml` 中添加对应的模板配置。
3. 运行初始化脚本。

### 字段联动 (Advanced)
在 `fields` 中可预留 `linkage` 属性供前端消费：
```yaml
- key: "task_list"
  linkage:
    trigger: "project_select"
    api: "/api/tasks/?project_id={value}"
```
*注：目前后端脚本仅存储此配置，需前端配合实现动态逻辑。*
