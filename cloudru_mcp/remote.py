"""Private, pre-provisioned bearer credentials for Streamable HTTP.
No browser OAuth/login flow; bearer hashes are installed by the operator.
"""
import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlsplit
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from .config import SafeError


class BearerVerifier:
    def __init__(self, digest, resource, expires):
        if not re.fullmatch(r'[a-f0-9]{64}',digest) or expires<=time.time():
            raise SafeError('AUTH: configure a SHA256 MCP token hash and future expiry')
        self.digest,self.resource,self.expires=digest,resource,expires

    async def verify_token(self, token):
        if time.time()>=self.expires or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),self.digest):
            return None
        return AccessToken(token=token,client_id='sales-operator',scopes=['sales'],
                           resource=self.resource,expires_at=self.expires)


def options():
    url=os.environ.get('CLOUDRU_MCP_PUBLIC_URL','')
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path!='/mcp':
        raise SafeError('CONFIG: MCP public URL must be https://host/mcp')
    try: expiry=int(os.environ.get('CLOUDRU_MCP_TOKEN_EXPIRES','0'))
    except ValueError: raise SafeError('CONFIG: token expiry must be Unix seconds') from None
    return dict(host='127.0.0.1',port=8000,stateless_http=True,json_response=True,
        token_verifier=BearerVerifier(os.environ.get('CLOUDRU_MCP_TOKEN_SHA256',''),url,expiry),
        auth=AuthSettings(issuer_url=f'{u.scheme}://{u.netloc}',resource_server_url=url,
                          required_scopes=['sales'],validate_token_resource=True),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[u.netloc,'127.0.0.1:8000'],allowed_origins=[f'https://{u.netloc}']))
