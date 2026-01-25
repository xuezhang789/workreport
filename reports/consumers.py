import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import Task, Project
from .services.sla import calculate_sla_info


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_authenticated:
            self.group_name = f'user_{self.user.id}'
            
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if self.user.is_authenticated:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        data = json.loads(text_data)
        notification_type = data.get('type', '')
        
        if notification_type == 'mark_as_read':
            notification_id = data.get('notification_id')
            # 实现标记通知为已读的逻辑
            await self.send(text_data=json.dumps({
                'message': f'Notification {notification_id} marked as read'
            }))

    async def send_notification(self, event):
        await self.send(text_data=json.dumps({
            'type': event['type'],
            'message': event['message'],
            'data': event.get('data', {}),
            'timestamp': event.get('timestamp', ''),
        }))


class TaskConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        self.project_id = self.scope['url_route']['kwargs']['project_id']
        
        if self.user.is_authenticated:
            # 检查用户是否有权限访问该项目
            has_permission = await self.check_project_permission(self.user, self.project_id)
            if has_permission:
                self.group_name = f'project_{self.project_id}'
                
                await self.channel_layer.group_add(
                    self.group_name,
                    self.channel_name
                )
                
                await self.accept()
            else:
                await self.close()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if self.user.is_authenticated:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    @database_sync_to_async
    def check_project_permission(self, user, project_id):
        try:
            project = Project.objects.get(id=project_id)
            return (user.has_perm('reports.view_project') or 
                   user.is_staff or 
                   project.owner == user or 
                   user in project.members.all() or 
                   user in project.managers.all())
        except Project.DoesNotExist:
            return False

    async def receive(self, text_data):
        data = json.loads(text_data)
        task_action = data.get('action', '')
        
        if task_action == 'update_status':
            task_id = data.get('task_id')
            new_status = data.get('status')
            
            # 更新任务状态
            updated = await self.update_task_status(task_id, new_status, self.user)
            
            if updated:
                # 向项目组广播任务状态更新
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        'type': 'task_updated',
                        'task_id': task_id,
                        'status': new_status,
                        'updated_by': self.user.username,
                    }
                )

    @database_sync_to_async
    def update_task_status(self, task_id, new_status, user):
        try:
            task = Task.objects.get(id=task_id)
            old_status = task.status
            task.status = new_status
            task.save()
            
            # 创建任务历史记录
            from .models import TaskHistory
            TaskHistory.objects.create(
                task=task,
                user=user,
                field='status',
                old_value=old_status,
                new_value=new_status
            )
            
            return True
        except Task.DoesNotExist:
            return False

    async def task_updated(self, event):
        await self.send(text_data=json.dumps({
            'type': 'task_updated',
            'task_id': event['task_id'],
            'status': event['status'],
            'updated_by': event['updated_by'],
        }))