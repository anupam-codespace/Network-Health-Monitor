from collections.abc import AsyncGenerator
import os
from pathlib import Path
import ssl
import subprocess
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from netwatch.auth import seed_api_keys
from netwatch.config import settings
from netwatch.db import get_db
from netwatch.main import create_app
from netwatch.models import Base


@pytest.fixture(scope="session")
def tls_cert_and_key(tmp_path_factory) -> tuple[str, str]:
    """Generates a temporary self-signed X.509 certificate and private key for local TLS tests."""
    temp_dir = tmp_path_factory.mktemp("tls_certs")
    cert_path = temp_dir / "test_cert.pem"
    key_path = temp_dir / "test_key.pem"

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "30",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return str(cert_path), str(key_path)


@pytest.fixture
def server_ssl_context(tls_cert_and_key: tuple[str, str]) -> ssl.SSLContext:
    """Configures server-side SSLContext loading the generated test certificate and key."""
    cert_path, key_path = tls_cert_and_key
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return context


@pytest.fixture
def client_ssl_context(tls_cert_and_key: tuple[str, str]) -> ssl.SSLContext:
    """Configures client-side SSLContext trusting the generated test CA certificate."""
    cert_path, _ = tls_cert_and_key
    context = ssl.create_default_context(cafile=cert_path)
    context.check_hostname = False
    return context


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provides an authenticated AsyncClient bound to the FastAPI application."""
    app = create_app()

    # Create tables and seed credentials in test database
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        await seed_api_keys(session)

    async def _test_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = _test_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()
