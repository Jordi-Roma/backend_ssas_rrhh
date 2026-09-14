from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ssas.auth.application.use_cases.refresh_token import RefreshToken
from ssas.core.security.dependencies import CurrentUser
from ssas.infrastructure.database.base import Base, import_all_models
from ssas.main import app
from ssas.usuarios.infrastructure.http.router import _target_empresa


def test_schema_contains_only_current_scope_tables() -> None:
    import_all_models()
    assert set(Base.metadata.tables) == {
        "empresa",
        "usuario",
        "rol",
        "permiso",
        "usuario_rol",
        "rol_permiso",
        "refresh_token",
        "password_reset_token",
        "email_verification_token",
        "bitacora",
        "departamento",
        "cargo",
        "habilidad",
        "vacante",
        "vacante_habilidad",
        "postulante",
        "etapa_reclutamiento",
        "motivo_rechazo",
        "postulacion",
        "postulacion_nota",
        "modulo",
        "empresa_modulo",
        "parametro_legal",
        "parametro_valor",
        "plan_suscripcion",
        "suscripcion",
    }


def test_openapi_does_not_expose_deferred_modules() -> None:
    paths = set(app.openapi()["paths"])
    assert not any("planes" in path for path in paths)
    assert not any("suscripciones" in path for path in paths)
    assert not any(path.startswith("/api/v1/platform") for path in paths)
    assert "/api/v1/parametros-legales" in paths


def test_login_examples_are_valid_request_bodies() -> None:
    login_schema = app.openapi()["components"]["schemas"]["LoginSchema"]
    examples = login_schema["examples"]

    assert examples
    assert all("summary" not in example and "value" not in example for example in examples)
    assert all("password" in example for example in examples)


def test_openapi_is_grouped_and_describes_every_business_operation() -> None:
    schema = app.openapi()
    expected_tags = {
        "Autenticación",
        "Usuarios",
        "Empresas",
        "Roles y permisos",
        "Bitácora",
        "Departamentos",
        "Cargos",
        "Vacantes",
        "Portal público",
        "Postulaciones",
        "Módulos",
        "Dashboard",
        "Estado",
        "Configuración",
    }

    assert {tag["name"] for tag in schema["tags"]} == expected_tags
    assert "/" not in schema["paths"]
    assert "/health" in schema["paths"]
    assert "/api/v1/auth/health" not in schema["paths"]

    for operations in schema["paths"].values():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert operation.get("summary")
            assert operation.get("description")
            assert set(operation.get("tags", [])) <= expected_tags


def test_openapi_explains_multitenant_scope_and_login_lock() -> None:
    schema = app.openapi()
    login_responses = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]
    assert "423" in login_responses

    user_parameters = schema["paths"]["/api/v1/usuarios"]["get"]["parameters"]
    empresa_parameter = next(item for item in user_parameters if item["name"] == "empresa_id")
    assert "plataforma" in empresa_parameter["description"].lower()
    assert "propia empresa" in empresa_parameter["description"].lower()


def test_openapi_exposes_recoverable_company_and_user_deletion() -> None:
    paths = app.openapi()["paths"]

    assert "delete" in paths["/api/v1/empresas/{empresa_id}"]
    assert "patch" in paths["/api/v1/empresas/{empresa_id}/restaurar"]
    assert "delete" in paths["/api/v1/usuarios/{usuario_id}"]
    assert "patch" in paths["/api/v1/usuarios/{usuario_id}/restaurar"]

    company_description = paths["/api/v1/empresas/{empresa_id}"]["delete"]["description"]
    user_description = paths["/api/v1/usuarios/{usuario_id}"]["delete"]["description"]
    assert "lógicamente" in company_description
    assert "revoca" in user_description


def test_platform_admin_can_select_target_scope() -> None:
    current = CurrentUser(id="admin", empresa_id=None, roles=["SUPER_ADMIN"])
    assert _target_empresa(current, None) is None
    assert _target_empresa(current, "empresa-a") == "empresa-a"


def test_company_admin_is_forced_to_own_company() -> None:
    current = CurrentUser(id="admin", empresa_id="empresa-a", roles=["ADMIN_EMPRESA"])
    assert _target_empresa(current, None) == "empresa-a"
    assert _target_empresa(current, "empresa-a") == "empresa-a"


def test_company_admin_cannot_select_another_company() -> None:
    current = CurrentUser(id="admin", empresa_id="empresa-a", roles=["ADMIN_EMPRESA"])
    try:
        _target_empresa(current, "empresa-b")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Se permitió operar sobre otra empresa")


@pytest.mark.asyncio
async def test_refresh_token_supports_platform_identity() -> None:
    class Tokens:
        def decode_token(self, _token, expected_type):
            assert expected_type == "refresh"
            return {"sub": "admin", "tid": None, "jti": "token-id"}

        def fingerprint(self, _token):
            return "hash"

        def create_refresh_token(self, subject, empresa_id):
            assert subject == "admin" and empresa_id is None
            return "new-refresh", "new-id", datetime.now(UTC) + timedelta(days=1)

        def create_access_token(self, subject, empresa_id, **_kwargs):
            assert subject == "admin" and empresa_id is None
            return "new-access"

    class TokenRepository:
        async def get_active_refresh_token(self, _token_id):
            return SimpleNamespace(empresa_id=None, token_hash="hash")

        async def revoke_refresh_token(self, _token_id):
            return None

        async def save_refresh_token(self, **values):
            assert values["empresa_id"] is None

    class Users:
        async def get_by_id(self, _user_id, empresa_id):
            assert empresa_id is None
            return SimpleNamespace(
                is_active=True,
                empresa_is_active=False,
                empresa_id=None,
                roles=["SUPER_ADMIN"],
                email_verified=True,
                locked_until=None,
                must_change_password=False,
            )

    result = await RefreshToken(Tokens(), TokenRepository(), Users()).execute("refresh")
    assert result["access_token"] == "new-access"
    assert result["refresh_token"] == "new-refresh"
