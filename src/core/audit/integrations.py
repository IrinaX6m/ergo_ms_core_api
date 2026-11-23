"""Регистрация публичного API аудита в ModuleBridge.

Модули пишут в журнал только через `bridge.call(AUDIT_RECORD, ...)` и
описывают свои действия через `bridge.provide_many(AUDIT_ACTION_DEFINITIONS_GROUP, ...)`,
без прямого импорта моделей/сервиса этого приложения.
"""

import uuid

from src.core.integrations import bridge
from src.core.integrations.module_contracts import (
    AUDIT_ACTION_DEFINITIONS_GROUP,
    AUDIT_LIST_EVENTS,
    AUDIT_RECORD,
)

from . import catalog
from .core_actions import CORE_AUDIT_SECTION, CORE_SETTINGS_SECTION
from .models import AuditEvent
from .service import AuditService

LIST_EVENTS_MAX_LIMIT = 200
# Ключ строки ленты выводится из pk, но сам pk наружу не уходит.
_EVENT_KEY_NAMESPACE = uuid.UUID('5f0c2a3e-8a51-4d0b-9c3e-6a7d2b9e4f10')


@bridge.provide_op(AUDIT_RECORD)
def _record(
    *,
    action,
    source_module='',
    actor=None,
    request=None,
    entity=None,
    changes=None,
    meta=None,
    severity='info',
    scope=None,
):
    """Зафиксировать действие пользователя в едином журнале.

    Инициатор, IP, User-Agent, измерения (scope) и request_id подхватываются из
    контекста запроса автоматически — обычно достаточно передать `action`
    и (по желанию) `entity` / `changes`.

    scope (dict|None) — переопределения измерений журнала (audit.scope_dimensions).
    """
    kwargs = dict(
        action=action,
        source_module=source_module,
        request=request,
        entity=entity,
        changes=changes,
        meta=meta,
        severity=severity,
    )
    if actor is not None:
        kwargs['actor'] = actor
    if scope is not None:
        kwargs['scope'] = scope

    AuditService.record(**kwargs)


def _clean_names(values):
    return [str(value).strip() for value in (values or []) if str(value or '').strip()]


def _event_row(event):
    spec = catalog.get_action_spec(event.source_module or '', event.action or '')
    actor = event.actor
    actor_public_id = getattr(actor, 'public_id', None) if actor is not None else None
    return {
        'key': str(uuid.uuid5(_EVENT_KEY_NAMESPACE, str(event.pk))),
        'created_at': event.created_at.isoformat(),
        'action': event.action,
        'action_label': spec['label'] if spec else event.action,
        'icon': spec['icon'] if spec else '',
        'entity_type': event.entity_type,
        'entity_ref': event.entity_ref,
        'entity_label': event.entity_label,
        'changes': event.changes if isinstance(event.changes, list) else [],
        'actor_user_public_id': str(actor_public_id) if actor_public_id else '',
        'actor_label': event.actor_label,
    }


@bridge.provide_op(AUDIT_LIST_EVENTS)
def _list_events(*, source_module, entity_types=None, actions=None, with_actor=False, limit=20, offset=0):
    """События одного модуля-источника, новые сверху.

    Модуль читает так только свои записи, чтобы показать их на своём экране.
    Пустой source_module ничего не отдаёт: общей ленты через мост нет.
    with_actor=True оставляет только действия людей, без записей фоновых задач.
    """
    module = str(source_module or '').strip()
    if not module:
        return {'count': 0, 'results': []}
    limit = max(0, min(int(limit or 0), LIST_EVENTS_MAX_LIMIT))
    offset = max(0, int(offset or 0))
    queryset = AuditEvent.objects.filter(source_module=module)
    types = _clean_names(entity_types)
    if types:
        queryset = queryset.filter(entity_type__in=types)
    names = _clean_names(actions)
    if names:
        queryset = queryset.filter(action__in=names)
    if with_actor:
        queryset = queryset.filter(actor__isnull=False)
    count = queryset.count()
    if not limit:
        return {'count': count, 'results': []}
    events = queryset.select_related('actor').order_by('-created_at', '-id')[offset:offset + limit]
    return {'count': count, 'results': [_event_row(event) for event in events]}


# Каталог действий самого ядра.
bridge.provide_many(
    AUDIT_ACTION_DEFINITIONS_GROUP, key=CORE_AUDIT_SECTION['module'], obj=CORE_AUDIT_SECTION,
)
bridge.provide_many(
    AUDIT_ACTION_DEFINITIONS_GROUP, key=CORE_SETTINGS_SECTION['module'], obj=CORE_SETTINGS_SECTION,
)
