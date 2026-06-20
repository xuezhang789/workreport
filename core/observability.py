import contextvars
import json
import logging
from datetime import datetime, timezone


request_id_context = contextvars.ContextVar('request_id', default='-')


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        request_id = request_id_context.get()
        if request_id == '-' and getattr(record, 'request', None) is not None:
            request_id = getattr(record.request, 'request_id', '-')
        record.request_id = request_id
        return True


class JsonFormatter(logging.Formatter):
    RESERVED = {
        'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
        'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs',
        'message', 'msg', 'name', 'pathname', 'process', 'processName',
        'relativeCreated', 'stack_info', 'thread', 'threadName',
    }

    def format(self, record):
        payload = {
            'timestamp': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'request_id': getattr(record, 'request_id', '-'),
        }
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and key not in payload and not key.startswith('_'):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = str(value)
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)
