import json
from channels.generic.websocket import AsyncWebsocketConsumer

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return

        self.group_name = f"user_{self.user.id}"

        # 加入房间组
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            # 离开房间组
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    # 从房间组接收消息
    async def notification_message(self, event):
        message = event['message']
        notification_type = event.get('notification_type', 'system')
        title = event.get('title', 'Notification')
        created_at = event.get('created_at', '')

        # 发送消息到 WebSocket
        await self.send(text_data=json.dumps({
            'type': notification_type,
            'title': title,
            'message': message,
            'created_at': created_at
        }))
