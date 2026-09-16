from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.domain.exceptions import AuthError
from ssas.core.security.jwt import JWTService
from ssas.core.tenancy.context import get_current_empresa_id
from ssas.infrastructure.database.session import get_session
from ssas.roles.application.use_cases.check_permission import CheckPermission
from ssas.roles.domain.exceptions import PermissionDeniedError
from ssas.roles.infrastructure.persistence.repositories.authorization_repository import (
    SqlAlchemyAuthorizationRepository,
)

bearer_scheme = HTTPBearer(auto_error=False)
token_service = JWTService()


@dataclass(frozen=True)
class CurrentUser:
    """Quien ejecuta la petición.

    ``empresa_id is None`` significa administrador de la plataforma: opera sobre
    cualquier empresa, pero solo con los permisos ``platform:*`` que tenga asignados
    explícitamente. No hay ninguna excepción codificada por rol.
    """

    id: str
    empresa_id: str | None
    roles: list[str] = field(default_factory=list)
    must_change_password: bool = False

    @property
    def es_plataforma(self) -> bool:
        return self.empresa_id is None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
        )

    try:
        payload = token_service.decode_token(credentials.credentials, expected_type="access")
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        ) from exc

    user_id = payload.get("sub")
    empresa_id = payload.get("tid")
    roles = payload.get("roles", [])
    must_change_password = payload.get("must_change_password", False)
    current_empresa_id = get_current_empresa_id()

    if not isinstance(user_id, str) or not user_id.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    if empresa_id is not None and (not isinstance(empresa_id, str) or not empresa_id.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token no contiene una empresa válida",
        )
    if empresa_id != current_empresa_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La empresa del token no coincide con el contexto de la petición",
        )
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    return CurrentUser(
        id=user_id,
        empresa_id=empresa_id,
        roles=roles,
        must_change_password=bool(must_change_password),
    )


def require_permission(required_permission: str) -> Callable:
    async def dependency(
        request: Request,
        current_user: CurrentUser = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> CurrentUser:
        if current_user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Debes cambiar tu contraseña antes de continuar",
            )
        try:
            await CheckPermission(SqlAlchemyAuthorizationRepository(session)).execute(
                user_id=current_user.id,
                empresa_id=current_user.empresa_id,
                required_permission=required_permission,
            )
        except PermissionDeniedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc

        is_write = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        self_service_path = request.url.path.startswith(
            ("/api/v1/suscripcion", "/api/v1/usuarios/me")
        )
        if not current_user.es_plataforma and is_write and not self_service_path:
            from ssas.config.settings import settings
            from ssas.suscripciones.application.policy import (
                SubscriptionPolicy,
                SubscriptionPolicyError,
            )

            try:
                await SubscriptionPolicy(
                    session, settings.subscription_grace_days
                ).require_operational(current_user.empresa_id)
            except SubscriptionPolicyError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return current_user

    return dependency


def require_platform_permission(required_permission: str) -> Callable:
    """Igual que require_permission, pero además exige alcance de plataforma.

    Un ADMIN_EMPRESA nunca debería poder crear o suspender empresas, aunque
    alguien le asigne por error un permiso ``platform:*``.
    """

    async def dependency(
        current_user: CurrentUser = Depends(require_permission(required_permission)),
    ) -> CurrentUser:
        if not current_user.es_plataforma:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta operación es exclusiva de administradores de la plataforma",
            )
        return current_user

    return dependency


def require_empresa_permission(
    tenant_permission: str,
    platform_permission: str,
) -> Callable:
    """Autoriza el mismo recurso empresa para ambos alcances.

    El usuario de plataforma puede apuntar a cualquier ``empresa_id`` si tiene el
    permiso global. El usuario empresarial solo puede apuntar al identificador de
    su propio token y además necesita el permiso tenant correspondiente.
    """

    async def dependency(
        empresa_id: str,
        current_user: CurrentUser = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> CurrentUser:
        if current_user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Debes cambiar tu contraseña antes de continuar",
            )
        if not current_user.es_plataforma and current_user.empresa_id != empresa_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes operar sobre otra empresa",
            )
        required = platform_permission if current_user.es_plataforma else tenant_permission
        try:
            await CheckPermission(SqlAlchemyAuthorizationRepository(session)).execute(
                user_id=current_user.id,
                empresa_id=current_user.empresa_id,
                required_permission=required,
            )
        except PermissionDeniedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        return current_user

    return dependency


def require_scoped_permission(tenant_permission: str, platform_permission: str) -> Callable:
    """Selecciona el permiso según el alcance de la identidad autenticada."""

    async def dependency(
        current_user: CurrentUser = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> CurrentUser:
        if current_user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Debes cambiar tu contraseña antes de continuar",
            )
        required = platform_permission if current_user.es_plataforma else tenant_permission
        try:
            await CheckPermission(SqlAlchemyAuthorizationRepository(session)).execute(
                user_id=current_user.id,
                empresa_id=current_user.empresa_id,
                required_permission=required,
            )
        except PermissionDeniedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        return current_user

    return dependency
