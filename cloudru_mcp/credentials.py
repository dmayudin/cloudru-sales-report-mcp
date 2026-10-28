"""Run on the cloud host in a user-controlled terminal; never through a chat tool with secrets."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time


def save_exclusive(path, text):
    path=Path(path)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: f.write(text)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',default='/etc/cloudru-sales/secrets.env')
    p.add_argument('--token-output',default='/etc/cloudru-sales/client-token')
    args=p.parse_args()
    if not sys.stdin.isatty(): p.error('Use an interactive, user-controlled terminal; secret echo is forbidden')
    if Path(args.output).exists() or Path(args.token_output).exists(): p.error('Output already exists; do not overwrite active credentials')
    fields=[('CLOUDRU_KEY_ID','Cloud.ru: идентификатор ключа (Key ID)'),
            ('CLOUDRU_KEY_SECRET','Cloud.ru: секрет ключа (Key Secret)'),
            ('CLOUDRU_S3_ACCESS_KEY','Хранилище: ключ доступа, если уже подготовлен'),
            ('CLOUDRU_S3_SECRET_KEY','Хранилище: секрет, если уже подготовлен'),
            ('CLOUDRU_BI_API_TOKEN','BI: токен API, только если способ доступа уже подтверждён')]
    print('Ввод скрыт. Значения не будут показаны или отправлены в чат. Необязательные поля можно пропустить клавишей Enter.')
    values={k:getpass.getpass(label+': ') for k,label in fields}
    if not values['CLOUDRU_KEY_ID'] or not values['CLOUDRU_KEY_SECRET']:
        p.error('Нужны оба значения ключа Cloud.ru; файлы не созданы')
    values['CLOUDRU_CH_PASSWORD']=secrets.token_urlsafe(32)
    values['CLOUDRU_BI_CH_PASSWORD']=secrets.token_urlsafe(32)
    token=secrets.token_urlsafe(48)
    values['CLOUDRU_MCP_TOKEN_SHA256']=hashlib.sha256(token.encode()).hexdigest()
    values['CLOUDRU_MCP_TOKEN_EXPIRES']=str(int(time.time())+86400)
    if any('\n' in v or '\r' in v or '\x00' in v for v in values.values()): p.error('Invalid multiline value')
    quote=lambda s:'"'+s.replace('\\','\\\\').replace('"','\\"')+'"'
    save_exclusive(args.output,'\n'.join(k+'='+quote(v) for k,v in values.items() if v)+'\n')
    save_exclusive(args.token_output,token+'\n')
    print('Credentials saved with mode 0600. MCP client token saved separately; values were not printed.')


if __name__=='__main__': main()
