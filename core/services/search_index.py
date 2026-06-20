import re
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.urls import reverse

from core.models import SearchIndex


TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
SCOPE_TYPES = {
    'all': (
        SearchIndex.ObjectType.PROJECT,
        SearchIndex.ObjectType.TASK,
        SearchIndex.ObjectType.DAILY_REPORT,
    ),
    'projects': (SearchIndex.ObjectType.PROJECT,),
    'tasks': (SearchIndex.ObjectType.TASK,),
    'reports': (SearchIndex.ObjectType.DAILY_REPORT,),
}


@dataclass(frozen=True)
class SearchHit:
    object_type: str
    obj: object

    @property
    def category(self):
        return {
            SearchIndex.ObjectType.PROJECT: '项目 / Projects',
            SearchIndex.ObjectType.TASK: '任务 / Tasks',
            SearchIndex.ObjectType.DAILY_REPORT: '日报 / Reports',
        }[self.object_type]

    @property
    def icon(self):
        return {
            SearchIndex.ObjectType.PROJECT: '📂',
            SearchIndex.ObjectType.TASK: '✅',
            SearchIndex.ObjectType.DAILY_REPORT: '📝',
        }[self.object_type]

    @property
    def title(self):
        if self.object_type == SearchIndex.ObjectType.PROJECT:
            return f"{self.obj.name} ({self.obj.code})"
        if self.object_type == SearchIndex.ObjectType.TASK:
            return f"#{self.obj.id} {self.obj.title}"
        return f"{self.obj.date} {self.obj.get_role_display()} - {self.obj.user.get_full_name() or self.obj.user.username}"

    @property
    def url(self):
        if self.object_type == SearchIndex.ObjectType.PROJECT:
            return reverse('projects:project_detail', args=[self.obj.id])
        if self.object_type == SearchIndex.ObjectType.TASK:
            return reverse('tasks:task_view', args=[self.obj.id])
        return reverse('reports:report_detail', args=[self.obj.id])

    def as_command_result(self):
        return {
            'category': self.category,
            'title': self.title,
            'url': self.url,
            'icon': self.icon,
        }


def normalize_search_text(*parts):
    tokens = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple, set)):
            tokens.extend(normalize_search_text(*part).split())
            continue
        text = str(part).strip()
        if text:
            tokens.append(text.lower())
    return ' '.join(tokens)


def query_terms(query):
    return [match.group(0).lower() for match in TOKEN_RE.finditer(query or '')]


def sync_project(project):
    body = normalize_search_text(
        project.description,
        project.progress_note,
        getattr(project.owner, 'username', ''),
        getattr(project.owner, 'first_name', ''),
        getattr(project.owner, 'last_name', ''),
    )
    return SearchIndex.objects.update_or_create(
        object_type=SearchIndex.ObjectType.PROJECT,
        object_id=project.id,
        defaults={
            'title': normalize_search_text(project.name, project.code)[:255],
            'subtitle': project.code,
            'body': body,
            'search_text': normalize_search_text(project.name, project.code, body),
            'project_ids': [project.id],
            'user_id': project.owner_id,
        },
    )


def sync_task(task):
    project_label = ''
    if getattr(task, 'project_id', None):
        project_label = f"{task.project.name} {task.project.code}"
    body = normalize_search_text(
        task.content,
        task.url,
        task.status,
        task.priority,
        task.category,
        project_label,
        getattr(task.user, 'username', ''),
        getattr(task.user, 'first_name', ''),
        getattr(task.user, 'last_name', ''),
    )
    return SearchIndex.objects.update_or_create(
        object_type=SearchIndex.ObjectType.TASK,
        object_id=task.id,
        defaults={
            'title': task.title[:255],
            'subtitle': project_label[:255],
            'body': body,
            'search_text': normalize_search_text(task.id, task.title, body),
            'project_ids': [task.project_id] if task.project_id else [],
            'user_id': task.user_id,
        },
    )


def sync_daily_report(report):
    content = report.content or {}
    body = normalize_search_text(
        report.role,
        report.status,
        list(content.values()),
        report.project,
        getattr(report.user, 'username', ''),
        getattr(report.user, 'first_name', ''),
        getattr(report.user, 'last_name', ''),
    )
    project_ids = list(report.projects.values_list('id', flat=True)) if report.pk else []
    return SearchIndex.objects.update_or_create(
        object_type=SearchIndex.ObjectType.DAILY_REPORT,
        object_id=report.id,
        defaults={
            'title': f"{report.date} {report.get_role_display()}"[:255],
            'subtitle': report.user.get_full_name() or report.user.username,
            'body': body,
            'search_text': normalize_search_text(report.date, report.role, body),
            'project_ids': project_ids,
            'user_id': report.user_id,
        },
    )


def sync_instance(instance):
    from projects.models import Project
    from tasks.models import Task
    from work_logs.models import DailyReport

    if isinstance(instance, Project):
        return sync_project(instance)
    if isinstance(instance, Task):
        return sync_task(instance)
    if isinstance(instance, DailyReport):
        return sync_daily_report(instance)
    return None


def schedule_sync_instance(instance):
    model = type(instance)
    pk = instance.pk

    def _sync():
        try:
            refreshed = model.objects.get(pk=pk)
        except model.DoesNotExist:
            return
        sync_instance(refreshed)

    transaction.on_commit(_sync)


def delete_instance(instance):
    object_type = object_type_for_instance(instance)
    if object_type:
        SearchIndex.objects.filter(object_type=object_type, object_id=instance.pk).delete()


def object_type_for_instance(instance):
    from projects.models import Project
    from tasks.models import Task
    from work_logs.models import DailyReport

    if isinstance(instance, Project):
        return SearchIndex.ObjectType.PROJECT
    if isinstance(instance, Task):
        return SearchIndex.ObjectType.TASK
    if isinstance(instance, DailyReport):
        return SearchIndex.ObjectType.DAILY_REPORT
    return None


def rebuild_search_index(batch_size=500):
    from projects.models import Project
    from tasks.models import Task
    from work_logs.models import DailyReport

    SearchIndex.objects.all().delete()
    counts = {'projects': 0, 'tasks': 0, 'reports': 0}

    for project in Project.objects.select_related('owner').iterator(chunk_size=batch_size):
        sync_project(project)
        counts['projects'] += 1

    task_qs = Task.objects.select_related('project', 'user')
    for task in task_qs.iterator(chunk_size=batch_size):
        sync_task(task)
        counts['tasks'] += 1

    report_qs = DailyReport.objects.select_related('user').prefetch_related('projects')
    for report in report_qs.iterator(chunk_size=batch_size):
        sync_daily_report(report)
        counts['reports'] += 1

    return counts


def _base_document_queryset(query, object_types):
    qs = SearchIndex.objects.filter(object_type__in=object_types)
    if not query:
        return qs.none()

    if connection.vendor == 'postgresql':
        try:
            from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

            search_query = SearchQuery(query, search_type='websearch', config='simple')
            vector = (
                SearchVector('title', weight='A', config='simple') +
                SearchVector('subtitle', weight='B', config='simple') +
                SearchVector('body', weight='C', config='simple')
            )
            return (
                qs.annotate(rank=SearchRank(vector, search_query))
                .filter(rank__gte=0.001)
                .order_by('-rank', '-updated_at')
            )
        except Exception:
            pass

    terms = query_terms(query)
    if not terms:
        return qs.none()

    filters = Q()
    for term in terms:
        filters &= Q(search_text__icontains=term)

    return (
        qs.filter(filters)
        .annotate(
            match_priority=Case(
                When(title__icontains=query, then=Value(0)),
                When(subtitle__icontains=query, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by('match_priority', '-updated_at')
    )


def _ordered_objects(qs, object_ids):
    objects = qs.filter(id__in=object_ids).in_bulk(object_ids)
    return [objects[object_id] for object_id in object_ids if object_id in objects]


def _legacy_search_documents(user, query, scope='all', limit_per_type=10):
    from reports.utils import get_accessible_projects, get_accessible_reports, get_accessible_tasks
    from work_logs.models import DailyReport

    grouped = {'projects': [], 'tasks': [], 'reports': []}
    hits = []

    if scope in ('all', 'projects'):
        projects = get_accessible_projects(user).filter(
            Q(name__icontains=query) | Q(code__icontains=query) | Q(description__icontains=query)
        ).select_related('owner').distinct()[:limit_per_type]
        grouped['projects'] = list(projects)
        hits.extend(SearchHit(SearchIndex.ObjectType.PROJECT, obj) for obj in grouped['projects'])

    if scope in ('all', 'tasks'):
        tasks = get_accessible_tasks(user).filter(
            Q(title__icontains=query) | Q(content__icontains=query) | Q(id__icontains=query)
        ).select_related('project', 'user').distinct()[:limit_per_type]
        grouped['tasks'] = list(tasks)
        hits.extend(SearchHit(SearchIndex.ObjectType.TASK, obj) for obj in grouped['tasks'])

    if scope in ('all', 'reports'):
        reports = get_accessible_reports(user).filter(
            DailyReport.content_search_query(query)
        ).select_related('user').prefetch_related('projects').distinct()[:limit_per_type]
        grouped['reports'] = list(reports)
        hits.extend(SearchHit(SearchIndex.ObjectType.DAILY_REPORT, obj) for obj in grouped['reports'])

    return grouped, hits


def search_documents(user, query, scope='all', limit_per_type=10):
    from reports.utils import get_accessible_projects, get_accessible_reports, get_accessible_tasks

    object_types = SCOPE_TYPES.get(scope, SCOPE_TYPES['all'])
    candidate_limit = max(limit_per_type * 10, 50)
    candidates = list(_base_document_queryset(query, object_types)[:candidate_limit])
    if not candidates:
        return _legacy_search_documents(user, query, scope=scope, limit_per_type=limit_per_type)

    ids_by_type = {}
    for document in candidates:
        ids_by_type.setdefault(document.object_type, []).append(document.object_id)

    objects_by_type = {}
    if SearchIndex.ObjectType.PROJECT in ids_by_type:
        objects_by_type[SearchIndex.ObjectType.PROJECT] = {
            obj.id: obj
            for obj in _ordered_objects(
                get_accessible_projects(user).select_related('owner'),
                ids_by_type[SearchIndex.ObjectType.PROJECT],
            )
        }
    if SearchIndex.ObjectType.TASK in ids_by_type:
        objects_by_type[SearchIndex.ObjectType.TASK] = {
            obj.id: obj
            for obj in _ordered_objects(
                get_accessible_tasks(user).select_related('project', 'user'),
                ids_by_type[SearchIndex.ObjectType.TASK],
            )
        }
    if SearchIndex.ObjectType.DAILY_REPORT in ids_by_type:
        objects_by_type[SearchIndex.ObjectType.DAILY_REPORT] = {
            obj.id: obj
            for obj in _ordered_objects(
                get_accessible_reports(user).select_related('user').prefetch_related('projects'),
                ids_by_type[SearchIndex.ObjectType.DAILY_REPORT],
            )
        }

    grouped = {
        'projects': [],
        'tasks': [],
        'reports': [],
    }
    hits = []
    key_by_type = {
        SearchIndex.ObjectType.PROJECT: 'projects',
        SearchIndex.ObjectType.TASK: 'tasks',
        SearchIndex.ObjectType.DAILY_REPORT: 'reports',
    }

    for document in candidates:
        obj = objects_by_type.get(document.object_type, {}).get(document.object_id)
        if not obj:
            continue
        key = key_by_type[document.object_type]
        if len(grouped[key]) >= limit_per_type:
            continue
        hit = SearchHit(document.object_type, obj)
        grouped[key].append(obj)
        hits.append(hit)

    return grouped, hits


def search_users(user, query, limit=10):
    from core.permissions import has_manage_permission
    from reports.utils import get_accessible_projects

    User = get_user_model()
    if user.is_superuser or has_manage_permission(user):
        qs = User.objects.all()
    else:
        accessible_projects = get_accessible_projects(user)
        qs = User.objects.filter(
            Q(project_memberships__in=accessible_projects) |
            Q(managed_projects__in=accessible_projects) |
            Q(owned_projects__in=accessible_projects)
        ).distinct()

    return qs.filter(
        Q(username__icontains=query) |
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    ).order_by('username')[:limit]


def global_search(user, query, scope='all', limit_per_type=10):
    grouped, hits = search_documents(user, query, scope=scope, limit_per_type=limit_per_type)
    results = {
        'projects': grouped['projects'] if scope in ('all', 'projects') else [],
        'tasks': grouped['tasks'] if scope in ('all', 'tasks') else [],
        'reports': grouped['reports'] if scope in ('all', 'reports') else [],
        'users': [],
    }
    if scope in ('all', 'users'):
        results['users'] = list(search_users(user, query, limit=limit_per_type))
    return results, hits
