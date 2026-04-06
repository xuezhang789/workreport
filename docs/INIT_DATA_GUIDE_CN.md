# 初始化数据（Seed Data）教程

本文档说明本项目有哪些“初始化/种子数据”来源、每类数据初始化了什么，以及如何在不同环境（生产/开发/压测）正确加载。

---

## 1. 总览：初始化数据都在哪里

本项目初始化数据主要来自三类入口：

1) **管理命令（management commands）写库**  
2) **YAML / Python 常量定义模板**（再由管理命令写库）  
3) **CSV 生成 + CSV 导入**（用于海量 mock / 压测数据）

对应文件与入口如下：

- 日报模板（YAML）：[roles.yaml](file:///Users/lingchong/Downloads/wwwroot/workreport/reports/data/definitions/roles.yaml) + `python manage.py init_role_templates`
- 日报/任务标准模板（Python 常量）：[default_templates.py](file:///Users/lingchong/Downloads/wwwroot/workreport/reports/data/default_templates.py) + `python manage.py init_standard_templates`
- 项目阶段：`python manage.py init_project_phases`（硬编码写库）
- RBAC 角色/权限：`python manage.py init_rbac`（硬编码写库 + 迁移现有项目成员关系）
- 海量 CSV mock：`python scripts/generate_mock_data.py` + `python manage.py import_mock_data`
- ORM 生成测试/压测数据：`python manage.py generate_test_data` / `generate_chinese_data` / `generate_large_scale_data`

---

## 2. 推荐执行顺序（新环境）

下面顺序适合“首次部署 / 全新数据库”：

1. 迁移数据库
   - `python manage.py migrate`
2. 创建管理员
   - `python manage.py createsuperuser`
3. 初始化项目阶段（建议）
   - `python manage.py init_project_phases`
4. 初始化 RBAC（建议）
   - `python manage.py init_rbac`
5. 初始化模板（二选一）
   - 推荐（更可配置）：`python manage.py init_role_templates`
   - 或使用内置默认：`python manage.py init_standard_templates`

说明：

- `init_role_templates` 与 `init_standard_templates` 都会写 `RoleTemplate`，同一角色的模板会被后执行的命令覆盖；生产环境建议只选一种长期维护。
- 生产环境如果只需要基础功能：阶段 + RBAC + 模板即可满足常规使用。

---

## 3. 日报模板（推荐：YAML 配置）

### 3.1 初始化内容

YAML 文件：[roles.yaml](file:///Users/lingchong/Downloads/wwwroot/workreport/reports/data/definitions/roles.yaml) 的 `templates` 列表中每一项对应一个角色的日报模板，初始化时会写入两类数据：

- `work_logs.RoleTemplate`：作为“按角色的默认表单提示/示例”
- `work_logs.ReportTemplateVersion`：作为“模板中心（可选模板）的一条版本化模板”

入口命令：[init_role_templates.py](file:///Users/lingchong/Downloads/wwwroot/workreport/core/management/commands/init_role_templates.py)

### 3.2 YAML 字段说明（最常用）

每个模板项的关键字段：

- `role`：角色代号，必须在 `Profile.ROLE_CHOICES` 中（不合法会被跳过）
- `name`：模板名称（写入 `ReportTemplateVersion.name`）
- `hint`：填写提示（写入 `RoleTemplate.hint`）
- `version`：模板版本号（写入 `ReportTemplateVersion.version`）
- `sort_order`：排序权重（写入 `RoleTemplate.sort_order`）
- `fields`：字段定义列表（schema 信息 + 默认示例）
  - `key`：字段 key（会写入 placeholders，并用于拼接示例正文）
  - `label` / `required` / `type`：当前主要作为 schema 信息存储（便于未来更智能的渲染）
  - `default`：该字段的示例内容（Markdown 多行文本）
- `metrics`：指标定义（schema 信息存储）

写入规则要点：

- `placeholders[key] = field.default`  
- `placeholders['_schema']` 会保存 `{fields, metrics, version}`  
- `RoleTemplate.sample_md` / `ReportTemplateVersion.content` 会把所有 `fields[*].default` 用空行拼接成一段综合示例正文

### 3.3 运行方式

默认读取 `reports/data/definitions/roles.yaml`：

```bash
python manage.py init_role_templates
```

指定 YAML 路径：

```bash
python manage.py init_role_templates --config reports/data/definitions/roles.yaml --env prod
```

说明：

- 该命令使用 `update_or_create` 写库，重复执行是幂等的（会更新已有记录）。
- 本命令依赖 PyYAML（导入 `yaml`），如果你的环境只安装了 `requirements.txt`，可能需要额外安装 `PyYAML`。

### 3.4 如何新增/修改模板（推荐做法）

- 新增角色模板：在 `templates:` 下追加一段 `role: xxx` 的配置，并确保该角色存在于 `Profile.ROLE_CHOICES`
- 修改模板示例：修改对应 `fields[*].default`
- 需要“模板中心”出现新版：把 `version` 增加（例如从 2 升到 3）

---

## 4. 标准模板（Python 常量）

标准模板定义在：[default_templates.py](file:///Users/lingchong/Downloads/wwwroot/workreport/reports/data/default_templates.py)

- `DAILY_REPORT_TEMPLATES`：按角色提供 `name/role/hint/placeholders/sample_md`
- `TASK_TEMPLATES`：任务模板列表（`name/title/content`）

加载入口：[init_standard_templates.py](file:///Users/lingchong/Downloads/wwwroot/workreport/core/management/commands/init_standard_templates.py)（内部调用 [TemplateGenerator](file:///Users/lingchong/Downloads/wwwroot/workreport/reports/services/template_generator.py) 写库）

运行：

```bash
python manage.py init_standard_templates
```

说明：

- 该命令会为日报模板写入 `RoleTemplate` 和 `ReportTemplateVersion(version=1)`。
- 该命令会为任务模板写入 `tasks.TaskTemplateVersion(version=1)`。
- 如果你同时使用 YAML 方案与标准模板方案，请明确“谁最终生效”（后执行的命令会覆盖同角色的 `RoleTemplate` 内容）。

---

## 5. 项目阶段（ProjectPhaseConfig）

入口命令：[init_project_phases.py](file:///Users/lingchong/Downloads/wwwroot/workreport/projects/management/commands/init_project_phases.py)

初始化默认阶段（并会更新已存在阶段的进度与排序）：

- 项目启动 / Initiation（0%）
- 需求分析 / Requirements（10%）
- 系统设计 / Design（25%）
- 开发实施 / Implementation（30%）
- 测试验证 / Testing（75%）
- 部署上线 / Deployment（90%）
- 项目结项 / Closing（100%）

运行：

```bash
python manage.py init_project_phases
```

---

## 6. RBAC 角色与权限（以及对现有项目数据的迁移）

入口命令：[init_rbac.py](file:///Users/lingchong/Downloads/wwwroot/workreport/core/management/commands/init_rbac.py)

### 6.1 初始化内容

该命令会：

- 创建权限（`core.Permission`）：如 `project.view / project.manage / task.create ...`
- 创建角色（`core.Role`）：`project_owner / project_manager / project_member / global_manager`
- 为角色分配权限（`core.RolePermission`）
- 遍历现有项目，把 `Project.owner / Project.managers / Project.members` 迁移为 `UserRole(scope="project:{id}")` 的项目级角色绑定
- 将 `Profile.position in ['mgr','pm']` 的用户赋予全局 `global_manager`（`scope=None`）

### 6.2 运行方式

```bash
python manage.py init_rbac
```

说明：

- 内部使用 `get_or_create` 写入角色/权限/绑定关系，重复执行一般是安全的（会补齐缺失项）。
- RBAC 有缓存机制；角色分配时会清理对应用户缓存。

---

## 7. Mock 数据（CSV 生成 + 导入）

### 7.1 CSV 生成脚本

脚本：[generate_mock_data.py](file:///Users/lingchong/Downloads/wwwroot/workreport/scripts/generate_mock_data.py)

默认会生成非常大的数据量（用户/项目/任务/日报），输出到 `scripts/mock_data_output/` 目录。

运行：

```bash
python scripts/generate_mock_data.py
```

注意：

- 脚本依赖 `faker`、`tqdm` 等第三方包；如果你的环境只安装了 `requirements.txt`，需要额外安装这些依赖。
- `users.csv` 中的密码是“占位 hash”，导入后不保证可登录；若要可登录用户，建议使用下面的 ORM 生成命令（`generate_test_data` / `generate_chinese_data`）。

### 7.2 CSV 导入命令

入口：[import_mock_data.py](file:///Users/lingchong/Downloads/wwwroot/workreport/core/management/commands/import_mock_data.py)

运行（默认目录）：

```bash
python manage.py import_mock_data
```

指定目录与批大小：

```bash
python manage.py import_mock_data --dir scripts/mock_data_output --batch-size 5000
```

说明：

- 导入使用 `bulk_create(..., ignore_conflicts=True)`，若数据库已有同 ID 数据可能会被跳过而不是报错；通常建议在“空库/清库后”导入，避免数据不一致。

---

## 8. ORM 生成测试/压测数据（推荐用于本地开发与性能验证）

### 8.1 快速测试数据（可登录用户）

命令：[core generate_test_data](file:///Users/lingchong/Downloads/wwwroot/workreport/core/management/commands/generate_test_data.py)

运行：

```bash
python manage.py generate_test_data
```

效果（命令提示）：

- 1000 用户（统一密码：`password123`）
- 200 项目、2000 任务、10000 日报，并建立部分项目成员与日报关联

补充：

- 代码库中还存在一个同名命令 [reports generate_test_data](file:///Users/lingchong/Downloads/wwwroot/workreport/reports/management/commands/generate_test_data.py)，但由于 `INSTALLED_APPS` 顺序（`core` 在 `reports` 之后），实际执行的是 `core` 版本。

### 8.2 中文拟真大数据

命令：[generate_chinese_data.py](file:///Users/lingchong/Downloads/wwwroot/workreport/core/management/commands/generate_chinese_data.py)

运行示例：

```bash
python manage.py generate_chinese_data --users 1000 --projects 5000 --tasks 100000 --reports 1000000 --clear
```

说明：

- `--clear` 会清理现有业务数据（保留超级管理员），请谨慎在生产环境使用。
- 该命令依赖 `faker` 与 `pypinyin`（用于把中文姓名转成用户名）。
- 若数据库没有阶段配置，会自动调用 `init_project_phases` 作为兜底。

### 8.3 性能压测全量数据

命令：[generate_large_scale_data.py](file:///Users/lingchong/Downloads/wwwroot/workreport/core/management/commands/generate_large_scale_data.py)

运行示例：

```bash
python manage.py generate_large_scale_data --clear --projects 10000 --tasks 100000 --reports 1000000
```

说明：

- 覆盖模型更全（含审计、附件、模板版本等），适合压测与索引/查询优化验证。
- 同样会在 `--clear` 时执行大规模清理，请仅在专用环境使用。

