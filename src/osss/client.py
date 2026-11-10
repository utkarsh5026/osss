"""Create OpenSearch clients for local servers, self-managed clusters and AWS."""

from __future__ import annotations

from typing import Any, Optional, Tuple
from urllib.parse import urlparse


def _aws_auth(host: str, region: Optional[str], service: Optional[str]):
    import boto3
    from opensearchpy import AWSV4SignerAuth

    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        raise RuntimeError(
            "No AWS credentials found for SigV4 signing. In SageMaker the execution "
            "role is used automatically; elsewhere configure `aws configure` or env vars."
        )
    if region is None:
        # search-xyz.us-east-1.es.amazonaws.com / abc.us-east-1.aoss.amazonaws.com
        parts = host.split(".")
        for i, p in enumerate(parts):
            if p in ("es", "aoss") and i > 0:
                region = parts[i - 1]
                break
        region = region or session.region_name
    if service is None:
        service = "aoss" if ".aoss." in host else "es"
    return AWSV4SignerAuth(creds, region, service)


def _local_connection_class():
    from opensearchpy import RequestsHttpConnection

    class LocalConnection(RequestsHttpConnection):
        """Ignores HTTP(S)_PROXY env vars: localhost traffic must never be proxied."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.session.trust_env = False

    return LocalConnection


def connect(
    url: str = "http://127.0.0.1:9200",
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    aws_auth: Optional[bool] = None,
    aws_region: Optional[str] = None,
    aws_service: Optional[str] = None,
    verify_certs: bool = True,
    timeout: int = 60,
    **kwargs: Any,
):
    """Return an :class:`opensearchpy.OpenSearch` client.

    ``aws_auth`` defaults to ``True`` for ``*.amazonaws.com`` hosts when no
    username/password is given, so Amazon OpenSearch Service / Serverless work
    out of the box with the SageMaker execution role.
    """
    from opensearchpy import OpenSearch, RequestsHttpConnection

    if "://" not in url:
        url = "http://" + url
    u = urlparse(url)
    host = u.hostname or "127.0.0.1"
    scheme = u.scheme or "http"
    port = u.port or (443 if scheme == "https" else 9200)
    http_auth: Optional[Any] = None
    if username is not None:
        http_auth = (username, password or "")
    elif u.username:
        http_auth = (u.username, u.password or "")
    if aws_auth is None:
        aws_auth = http_auth is None and host.endswith("amazonaws.com")
    if aws_auth:
        http_auth = _aws_auth(host, aws_region, aws_service)
    local = host in ("127.0.0.1", "localhost", "::1")
    return OpenSearch(
        hosts=[{"host": host, "port": port, "scheme": scheme}],
        http_auth=http_auth,
        use_ssl=scheme == "https",
        verify_certs=verify_certs if scheme == "https" else False,
        ssl_show_warn=False,
        connection_class=_local_connection_class() if local else RequestsHttpConnection,
        timeout=timeout,
        max_retries=3,
        retry_on_timeout=True,
        **kwargs,
    )


def describe(client) -> Tuple[str, str]:
    """(distribution, version) of the cluster, e.g. ("opensearch", "3.9.0")."""
    info = client.info()
    v = info.get("version", {})
    return v.get("distribution", "opensearch"), v.get("number", "?")
