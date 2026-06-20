from decimal import Decimal, InvalidOperation

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


PREFIX = 'enc:v1:'


def _fernets():
    instances = []
    for key in settings.FIELD_ENCRYPTION_KEYS:
        try:
            instances.append(Fernet(key.encode('ascii')))
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured('FIELD_ENCRYPTION_KEYS contains an invalid Fernet key') from exc
    return instances


def encrypt_value(value):
    if value in (None, ''):
        return value
    text = str(value)
    if text.startswith(PREFIX):
        return text
    return PREFIX + _fernets()[0].encrypt(text.encode('utf-8')).decode('ascii')


def decrypt_value(value):
    if value in (None, '') or not str(value).startswith(PREFIX):
        return value
    token = str(value)[len(PREFIX):].encode('ascii')
    for fernet in _fernets():
        try:
            return fernet.decrypt(token).decode('utf-8')
        except InvalidToken:
            continue
    raise ValueError('Unable to decrypt sensitive field with configured keys')


class EncryptedTextField(models.TextField):
    description = 'Fernet-encrypted text'

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value)

    def to_python(self, value):
        if value is None or isinstance(value, str):
            return decrypt_value(value)
        return decrypt_value(str(value))

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_value(value)


class EncryptedDecimalField(EncryptedTextField):
    description = 'Fernet-encrypted decimal'

    def __init__(self, *args, max_digits=None, decimal_places=None, **kwargs):
        self.max_digits = max_digits
        self.decimal_places = decimal_places
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['max_digits'] = self.max_digits
        kwargs['decimal_places'] = self.decimal_places
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        value = decrypt_value(value)
        return self._decimal(value)

    def to_python(self, value):
        value = decrypt_value(value)
        return self._decimal(value)

    def get_prep_value(self, value):
        if value in (None, ''):
            return value
        decimal_value = self._decimal(value)
        return encrypt_value(format(decimal_value, 'f'))

    @staticmethod
    def _decimal(value):
        if value in (None, '') or isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f'Invalid encrypted decimal value: {value}') from exc


def encrypted_alias(storage_field):
    def getter(instance):
        return getattr(instance, storage_field)

    def setter(instance, value):
        setattr(instance, storage_field, value)

    return property(getter, setter)
