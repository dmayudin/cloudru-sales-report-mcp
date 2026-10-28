#!/usr/bin/env python3
"""User-operated, non-echoing bootstrap credential handoff. No application server."""
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import UUID
import base64
import httpx

ROOT=Path(__file__).resolve().parents[1]
MARKER=ROOT/'bootstrap-connection.json'


def private_write(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(value,f)


def main():
    if not sys.stdin.isatty():
        print('Нужен терминал с защищённым вводом. Не передавайте ключ через аргументы команды.')
        return 2
    if MARKER.exists():
        print('Подключение уже подготовлено. Сообщите агенту: подключение существует. Повторный ввод не нужен.')
        return 2
    print('Подключение Cloud.ru для тестового отчёта. Облачные ресурсы не создаются.')
    print('Ключ передаётся только в IAM Cloud.ru по HTTPS. Ввод не отображается.')
    print('После успешной проверки ключ временно сохранится на этом компьютере в файле, доступном только вашему пользователю, для дальнейших API-запросов агента.')
    try:
        key_id=getpass.getpass('Вставьте Key ID и нажмите Enter: ').strip()
        secret=getpass.getpass('Вставьте Key Secret и нажмите Enter: ').strip()
        if not key_id or not secret or any(c in key_id+secret for c in '\r\n\x00'):
            print('Оба значения должны быть заполнены одной строкой. Файлы не созданы.')
            return 2
        with httpx.Client(timeout=30,follow_redirects=False,trust_env=False) as client:
            response=client.post('https://iam.api.cloud.ru/api/v2/auth/token',json={'keyId':key_id,'secret':secret})
        if response.status_code!=200:
            print(f'Cloud.ru не подтвердил доступ (HTTP {response.status_code}). Ключ не сохранён. Сообщите агенту только этот код.')
            return 1
        data=response.json()
        token=data.get('access_token') or data.get('token')
        if not isinstance(token,str) or not token:
            print('Ответ Cloud.ru отличается от ожидаемого. Ключ не сохранён.')
            return 1
        project_hint=None
        try:
            claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'==='))
            project_hint=str(UUID(claims['project_id']))
        except (ValueError,KeyError,IndexError,TypeError): pass
        folder=Path(tempfile.mkdtemp(prefix='cloudru-sales-access-'))
        os.chmod(folder,0o700)
        target=folder/'credentials.json'
        private_write(target,{'key_id':key_id,'key_secret':secret})
        try:
            private_write(MARKER,{'status':'iam_authenticated','credentials_file':str(target),
                'project_hint':project_hint,'project_scope_verified':False,'cloud_resources_created':False})
        except Exception:
            target.unlink();folder.rmdir()
            raise
        print('Доступ к IAM подтверждён. Напишите агенту: готово. Секреты в чат не копируйте.')
        return 0
    except (KeyboardInterrupt,EOFError):
        print('\nВвод отменён.')
        return 1
    except Exception:
        print('Подключение не завершено. Сообщите агенту об ошибке без ключей; подробности скрыты.')
        return 1


if __name__=='__main__': raise SystemExit(main())
