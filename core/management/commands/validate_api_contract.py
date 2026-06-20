from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import NoReverseMatch, reverse


HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete', 'options', 'head'}


class Command(BaseCommand):
    help = "Validate the OpenAPI contract and its Django route mappings."

    def add_arguments(self, parser):
        parser.add_argument(
            '--contract',
            default=None,
            help='Path to the OpenAPI YAML file. Defaults to docs/api/openapi.yaml.',
        )

    def handle(self, *args, **options):
        contract_path = Path(options['contract'] or Path(settings.BASE_DIR) / 'docs' / 'api' / 'openapi.yaml')
        if not contract_path.exists():
            raise CommandError(f'OpenAPI contract not found: {contract_path}')

        try:
            data = yaml.safe_load(contract_path.read_text(encoding='utf-8'))
        except yaml.YAMLError as exc:
            raise CommandError(f'Invalid OpenAPI YAML: {exc}') from exc

        errors = self._validate_contract(data)
        if errors:
            raise CommandError('OpenAPI contract validation failed:\n- ' + '\n- '.join(errors))

        self.stdout.write(self.style.SUCCESS(f'OpenAPI contract validated: {contract_path}'))

    def _validate_contract(self, data):
        errors = []
        if not isinstance(data, dict):
            return ['contract root must be a mapping']
        if not data.get('openapi'):
            errors.append('missing openapi version')
        if not data.get('info'):
            errors.append('missing info section')
        paths = data.get('paths')
        if not isinstance(paths, dict) or not paths:
            errors.append('paths section must not be empty')
            return errors

        operation_ids = set()
        for path, path_item in paths.items():
            if not str(path).startswith('/'):
                errors.append(f'{path}: path must start with /')
                continue
            if not isinstance(path_item, dict):
                errors.append(f'{path}: path item must be a mapping')
                continue

            for method, operation in path_item.items():
                if method not in HTTP_METHODS:
                    continue
                label = f'{method.upper()} {path}'
                if not isinstance(operation, dict):
                    errors.append(f'{label}: operation must be a mapping')
                    continue

                operation_id = operation.get('operationId')
                if not operation_id:
                    errors.append(f'{label}: missing operationId')
                elif operation_id in operation_ids:
                    errors.append(f'{label}: duplicate operationId {operation_id}')
                else:
                    operation_ids.add(operation_id)

                if not operation.get('responses'):
                    errors.append(f'{label}: missing responses')

                route_name = operation.get('x-django-name')
                if route_name:
                    kwargs = operation.get('x-django-kwargs') or {}
                    try:
                        reversed_path = reverse(route_name, kwargs=kwargs)
                    except NoReverseMatch as exc:
                        errors.append(f'{label}: cannot reverse {route_name}: {exc}')
                        continue
                    expected_path = self._substitute_path_kwargs(path, kwargs)
                    if reversed_path != expected_path:
                        errors.append(
                            f'{label}: route {route_name} resolves to {reversed_path}, '
                            f'expected {expected_path}'
                        )

        return errors

    @staticmethod
    def _substitute_path_kwargs(path, kwargs):
        expected = path
        for key, value in kwargs.items():
            expected = expected.replace('{' + key + '}', str(value))
        return expected
