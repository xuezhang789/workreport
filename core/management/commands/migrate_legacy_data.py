from django.core.management.base import BaseCommand
from django.db import transaction, connection
from reports.models import (
    Profile as OldProfile, SystemSetting as OldSystemSetting, Notification as OldNotification,
    UserPreference as OldUserPreference, ExportJob as OldExportJob,
    ProjectPhaseConfig as OldProjectPhaseConfig, Project as OldProject, ProjectAttachment as OldProjectAttachment,
    ProjectPhaseChangeLog as OldProjectPhaseChangeLog, ReminderRule as OldReminderRule,
    ProjectMemberPermission as OldProjectMemberPermission,
    Task as OldTask, TaskComment as OldTaskComment, TaskAttachment as OldTaskAttachment,
    TaskSlaTimer as OldTaskSlaTimer, TaskHistory as OldTaskHistory, TaskTemplateVersion as OldTaskTemplateVersion,
    RoleTemplate as OldRoleTemplate, DailyReport as OldDailyReport, ReportMiss as OldReportMiss,
    ReportTemplateVersion as OldReportTemplateVersion, AuditLog as OldAuditLog
)
from core.models import (
    Profile, SystemSetting, Notification, UserPreference, ExportJob
)
from projects.models import (
    ProjectPhaseConfig, Project, ProjectAttachment, ProjectPhaseChangeLog, ReminderRule, ProjectMemberPermission
)
from tasks.models import (
    Task, TaskComment, TaskAttachment, TaskSlaTimer, TaskHistory, TaskTemplateVersion
)
from work_logs.models import (
    RoleTemplate, DailyReport, ReportMiss, ReportTemplateVersion
)
from audit.models import AuditLog

class Command(BaseCommand):
    help = 'Migrate data from legacy reports app to new modular apps'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Starting data migration...")

        # 1. Core
        self.migrate_model(OldSystemSetting, SystemSetting)
        # self.migrate_model(OldPermissionMatrix, PermissionMatrix) # Removed deprecated model
        self.migrate_model(OldProfile, Profile)
        self.migrate_model(OldUserPreference, UserPreference)
        self.migrate_model(OldNotification, Notification)
        self.migrate_model(OldExportJob, ExportJob)

        # 2. Projects
        self.migrate_model(OldProjectPhaseConfig, ProjectPhaseConfig)
        self.migrate_model(OldProject, Project, m2m_fields=['members', 'managers'])
        self.migrate_model(OldProjectAttachment, ProjectAttachment)
        self.migrate_model(OldProjectPhaseChangeLog, ProjectPhaseChangeLog)
        self.migrate_model(OldReminderRule, ReminderRule)
        self.migrate_model(OldProjectMemberPermission, ProjectMemberPermission)

        # 3. Tasks
        self.migrate_model(OldTask, Task, m2m_fields=['collaborators'])
        self.migrate_model(OldTaskComment, TaskComment)
        self.migrate_model(OldTaskAttachment, TaskAttachment)
        self.migrate_model(OldTaskSlaTimer, TaskSlaTimer)
        self.migrate_model(OldTaskHistory, TaskHistory)
        self.migrate_model(OldTaskTemplateVersion, TaskTemplateVersion)

        # 4. Work Logs
        self.migrate_model(OldRoleTemplate, RoleTemplate)
        self.migrate_model(OldDailyReport, DailyReport, m2m_fields=['projects'])
        self.migrate_model(OldReportMiss, ReportMiss)
        self.migrate_model(OldReportTemplateVersion, ReportTemplateVersion)

        # 5. Audit
        self.migrate_model(OldAuditLog, AuditLog)

        self.stdout.write(self.style.SUCCESS("Data migration completed successfully!"))

    def migrate_model(self, OldModel, NewModel, fk_map=None, m2m_fields=None):
        model_name = NewModel.__name__
        self.stdout.write(f"Migrating {model_name}...")
        count = 0
        fk_map = fk_map or {}
        m2m_fields = m2m_fields or []

        for old_obj in OldModel.objects.all():
            data = {}
            for field in NewModel._meta.fields:
                if field.name == 'id':
                    data['id'] = old_obj.id
                    continue
                
                old_field_name = fk_map.get(field.name, field.name)
                
                if field.is_relation and (field.many_to_one or field.one_to_one):
                    # FK or OneToOne, use _id attribute
                    # field.attname is 'user_id'
                    # We assume old model has same field name, so same _id name
                    # But we need to check if old model has that attribute.
                    # Usually old_obj.user_id exists.
                    if hasattr(old_obj, field.attname):
                        data[field.attname] = getattr(old_obj, field.attname)
                else:
                    if hasattr(old_obj, old_field_name):
                        data[field.name] = getattr(old_obj, old_field_name)

            new_obj = NewModel(**data)
            new_obj.save()
            
            # Handle M2M
            for m2m_field in m2m_fields:
                if hasattr(old_obj, m2m_field):
                    old_m2m = getattr(old_obj, m2m_field)
                    new_m2m = getattr(new_obj, m2m_field)
                    # Use IDs to avoid model mismatch
                    new_m2m.set([obj.id for obj in old_m2m.all()])

            count += 1

        self.stdout.write(f"  Migrated {count} {model_name}s")
