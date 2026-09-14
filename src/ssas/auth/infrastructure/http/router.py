import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.application.services.auth_email_service import AuthEmailService
from ssas.auth.application.use_cases.change_password import ChangePassword
from ssas.auth.application.use_cases.get_current_user import GetCurrentUser
from ssas.auth.application.use_cases.login_user import LoginUser
from ssas.auth.application.use_cases.logout_user import LogoutUser
from ssas.auth.application.use_cases.refresh_token import RefreshToken
from ssas.auth.application.use_cases.request_email_verification import RequestEmailVerification
from ssas.auth.application.use_cases.request_password_reset import RequestPasswordReset
from ssas.auth.application.use_cases.reset_password import ResetPassword
from ssas.auth.application.use_cases.verify_email import VerifyEmail
from ssas.auth.domain.exceptions import (
    AccountLockedError,
    AuthError,
    EmailDeliveryError,
    EmailNotVerifiedError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidPasswordError,
    InvalidTokenError,
    TokenExpiredError,
    UserNotFoundError,
)
from ssas.auth.infrastructure.email.smtp_sender import SMTPEmailSender
from ssas.auth.infrastructure.http.schemas import (
    ChangePasswordSchema,
    ForgotPasswordResponseSchema,
    ForgotPasswordSchema,
    LoginSchema,
    MessageSchema,
    RefreshTokenSchema,
    RegistroEmpresaRequest,
    RegistroEmpresaResponse,
    ResendVerificationSchema,
    ResetPasswordSchema,
    TokenPairSchema,
    UserSchema,
    VerifyEmailSchema,
)
from ssas.auth.infrastructure.persistence.repositories.auth_token_repository import (
    SqlAlchemyAuthTokenRepository,
)
from ssas.auth.infrastructure.persistence.repositories.user_repository import (
    SqlAlchemyUserRepository,
)
from ssas.auth.infrastructure.security.jwt_service import JWTService
from ssas.auth.infrastructure.security.password_hasher import Argon2PasswordHasher
from ssas.bitacora.application.events.auth_events import AuthEvents
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.core.api.openapi import AUTHENTICATED_RESPONSES, TAG_AUTH
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser
from ssas.core.security.dependencies import get_current_user as get_authenticated_user
from ssas.infrastructure.database.session import AsyncSessionLocal, get_session
from ssas.modulos.application.module_access import get_modulos_habilitados
from ssas.roles.infrastructure.persistence.repositories.authorization_repository import (
    SqlAlchemyAuthorizationRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=[TAG_AUTH])
token_service = JWTService()
password_hasher = Argon2PasswordHasher()
email_service = AuthEmailService(SMTPEmailSender(), settings.app_frontend_url)


def _raise_http_auth_error(exc: AuthError) -> None:
    if isinstance(exc, UserNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, InvalidPasswordError):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(exc, AccountLockedError):
        code = status.HTTP_423_LOCKED
    elif isinstance(exc, EmailNotVerifiedError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, EmailDeliveryError):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(
        exc,
        (InvalidCredentialsError, InvalidTokenError, TokenExpiredError, InactiveUserError),
    ):
        code = status.HTTP_401_UNAUTHORIZED
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=str(exc)) from exc


def _user_repository(session: AsyncSession) -> SqlAlchemyUserRepository:
    return SqlAlchemyUserRepository(session)


def _token_repository(session: AsyncSession) -> SqlAlchemyAuthTokenRepository:
    return SqlAlchemyAuthTokenRepository(session)


def _events(session: AsyncSession) -> AuthEvents:
    return AuthEvents(RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)))


def _request_context(request: Request) -> dict[str, str | None]:
    return {
        "source_ip": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }


async def _record_failed_login(user, request: Request) -> None:
    """Persiste el intento fallido aunque la petición principal termine con HTTP 401."""
    if user is None:
        return
    try:
        async with AsyncSessionLocal() as audit_session:
            await _user_repository(audit_session).record_failed_login(
                user.id,
                user.empresa_id,
                settings.app_max_login_attempts,
                settings.app_login_lock_minutes,
            )
            await _events(audit_session).login_failed(
                empresa_id=user.empresa_id,
                user_id=user.id,
                actor_label=user.email,
                **_request_context(request),
            )
            await audit_session.commit()
    except Exception:
        logger.exception("No se pudo registrar un intento fallido de inicio de sesión")


@router.get("/health", include_in_schema=False)
async def auth_health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/login",
    response_model=TokenPairSchema,
    summary="Iniciar sesión",
    description=(
        "Autentica mediante correo o nombre de usuario. Omite `empresa_slug` para una "
        "cuenta de plataforma; envíalo para buscar la cuenta dentro de una empresa. "
        "Los intentos fallidos se registran y pueden bloquear temporalmente la cuenta."
    ),
    responses={
        401: {"description": "Credenciales inválidas o cuenta inactiva."},
        403: {"description": "El correo aún no fue verificado."},
        423: {"description": "Cuenta bloqueada temporalmente por intentos fallidos."},
        503: {"description": "No se pudo acceder a una dependencia del servicio."},
    },
)
async def login_user(
    request: LoginSchema,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
):
    repository = _user_repository(session)
    login = str(request.email) if request.email is not None else (request.username or "")
    try:
        result = await LoginUser(
            repository,
            password_hasher,
            token_service,
            _token_repository(session),
        ).execute(**request.model_dump())
    except AuthError as exc:
        user = await repository.get_by_login(login, request.empresa_slug)
        if isinstance(exc, InvalidCredentialsError):
            await _record_failed_login(user, http_request)
        _raise_http_auth_error(exc)
    payload = token_service.decode_token(result["access_token"], expected_type="access")
    tid = payload.get("tid")
    await _events(session).login_success(
        empresa_id=str(tid) if tid is not None else None,
        user_id=str(payload["sub"]),
        actor_label=login,
        **_request_context(http_request),
    )
    return result


@router.post(
    "/refresh",
    response_model=TokenPairSchema,
    summary="Renovar sesión",
    description=(
        "Intercambia un refresh token activo por un nuevo par de tokens y revoca el "
        "refresh token anterior."
    ),
    responses={401: {"description": "Refresh token inválido, vencido o revocado."}},
)
async def refresh_token(
    request: RefreshTokenSchema,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await RefreshToken(
            token_service,
            _token_repository(session),
            _user_repository(session),
        ).execute(request.refresh_token)
    except AuthError as exc:
        _raise_http_auth_error(exc)


@router.post(
    "/logout",
    response_model=MessageSchema,
    summary="Cerrar sesión",
    description="Revoca el refresh token enviado. Requiere un access token válido.",
    responses=AUTHENTICATED_RESPONSES,
)
async def logout_user(
    request: RefreshTokenSchema,
    http_request: Request,
    current_user: CurrentUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        await LogoutUser(token_service, _token_repository(session)).execute(
            request.refresh_token,
            current_user.id,
            current_user.empresa_id,
        )
        await _events(session).logout(
            empresa_id=current_user.empresa_id,
            user_id=current_user.id,
            **_request_context(http_request),
        )
        return {"message": "Sesión cerrada correctamente"}
    except AuthError as exc:
        _raise_http_auth_error(exc)


@router.get(
    "/me",
    response_model=UserSchema,
    summary="Consultar mi perfil",
    description=(
        "Devuelve la identidad autenticada, su empresa cuando corresponda, roles, permisos "
        "efectivos, módulos habilitados y estado de seguridad. Es la fuente única que usa el "
        "cliente para construir el menú y decidir qué acciones muestra."
    ),
    responses=AUTHENTICATED_RESPONSES,
)
async def current_user(
    current_user: CurrentUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        user = await GetCurrentUser(_user_repository(session)).execute(
            current_user.id,
            current_user.empresa_id,
        )
    except AuthError as exc:
        _raise_http_auth_error(exc)

    permissions = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(
        current_user.id, current_user.empresa_id
    )
    modulos = (
        []
        if current_user.empresa_id is None
        else await get_modulos_habilitados(session, current_user.empresa_id)
    )
    return UserSchema.model_validate(user).model_copy(
        update={"permissions": sorted(permissions), "modulos": modulos}
    )


@router.post(
    "/password/forgot",
    response_model=ForgotPasswordResponseSchema,
    summary="Solicitar recuperación de contraseña",
    description=(
        "Solicita un enlace de recuperación sin revelar si la cuenta existe. Omite "
        "`empresa_slug` para cuentas de plataforma."
    ),
    responses={503: {"description": "El servicio de correo no está disponible."}},
)
async def forgot_password(
    request: ForgotPasswordSchema,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
):
    repository = _user_repository(session)
    raw_token = await RequestPasswordReset(
        repository,
        _token_repository(session),
        token_service,
        settings.app_password_reset_expire_minutes,
    ).execute(str(request.email), request.empresa_slug)
    if raw_token:
        user = await repository.get_by_login(str(request.email), request.empresa_slug)
        if user:
            try:
                await email_service.send_password_reset(user.email, raw_token)
            except EmailDeliveryError:
                logger.exception("No se pudo enviar el correo de recuperación")
            await _events(session).password_reset_requested(
                empresa_id=user.empresa_id,
                user_id=user.id,
                actor_label=user.email,
                **_request_context(http_request),
            )
    return {
        "message": "Si el correo existe, se envió un enlace de recuperación",
        "reset_token": raw_token
        if settings.app_env == "development" and settings.app_debug
        else None,
    }


@router.post(
    "/password/change",
    response_model=MessageSchema,
    summary="Cambiar mi contraseña",
    description=(
        "Valida la contraseña actual, aplica la política de seguridad, actualiza la clave "
        "y revoca las sesiones existentes."
    ),
    responses={
        **AUTHENTICATED_RESPONSES,
        422: {"description": "La contraseña actual o la nueva contraseña no son válidas."},
    },
)
async def change_password(
    request: ChangePasswordSchema,
    http_request: Request,
    current_user: CurrentUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        await ChangePassword(
            _user_repository(session), _token_repository(session), password_hasher
        ).execute(
            current_user.id,
            current_user.empresa_id,
            request.current_password,
            request.new_password,
        )
        await _events(session).password_changed(
            empresa_id=current_user.empresa_id,
            user_id=current_user.id,
            **_request_context(http_request),
        )
        return {"message": "Contraseña actualizada; vuelve a iniciar sesión"}
    except AuthError as exc:
        _raise_http_auth_error(exc)


@router.post(
    "/email/verification/resend",
    response_model=MessageSchema,
    summary="Reenviar verificación de correo",
    description=(
        "Genera un nuevo enlace cuando la cuenta existe y su correo continúa pendiente de "
        "verificación."
    ),
    responses={503: {"description": "El servicio de correo no está disponible."}},
)
async def resend_email_verification(
    request: ResendVerificationSchema,
    session: AsyncSession = Depends(get_session),
):
    result = await RequestEmailVerification(
        _user_repository(session),
        _token_repository(session),
        token_service,
        settings.app_email_verification_expire_minutes,
    ).execute(str(request.email), request.empresa_slug)
    if result:
        email, raw_token = result
        try:
            await email_service.send_email_verification(email, raw_token)
        except EmailDeliveryError:
            logger.exception("No se pudo enviar el correo de verificación")
    return {"message": "Si la cuenta existe y está pendiente, se envió la verificación"}


@router.post(
    "/email/verify",
    response_model=MessageSchema,
    summary="Verificar correo electrónico",
    description="Confirma el correo mediante un token de verificación vigente y de un solo uso.",
    responses={401: {"description": "Token inválido, vencido o utilizado previamente."}},
)
async def verify_email(
    request: VerifyEmailSchema,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        stored_token = await _token_repository(session).get_active_email_verification_token(
            token_service.fingerprint(request.token)
        )
        await VerifyEmail(
            _user_repository(session), _token_repository(session), token_service
        ).execute(request.token)
        if stored_token:
            await _events(session).email_verified(
                empresa_id=stored_token.empresa_id,
                user_id=stored_token.user_id,
                **_request_context(http_request),
            )
        return {"message": "Correo verificado correctamente"}
    except AuthError as exc:
        _raise_http_auth_error(exc)


@router.post(
    "/password/reset",
    response_model=MessageSchema,
    summary="Restablecer contraseña",
    description=(
        "Establece una contraseña nueva mediante el token de recuperación y revoca las "
        "sesiones anteriores."
    ),
    responses={
        401: {"description": "Token inválido, vencido o utilizado previamente."},
        422: {"description": "La contraseña nueva no cumple la política de seguridad."},
    },
)
async def reset_password(
    request: ResetPasswordSchema,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
):
    token_repository = _token_repository(session)
    try:
        stored_token = await token_repository.get_active_password_reset_token(
            token_service.fingerprint(request.token)
        )
        await ResetPassword(
            _user_repository(session),
            token_repository,
            token_service,
            password_hasher,
        ).execute(request.token, request.new_password)
        if stored_token:
            await _events(session).password_reset_completed(
                empresa_id=stored_token.empresa_id,
                user_id=stored_token.user_id,
                **_request_context(http_request),
            )
        return {"message": "Contraseña restablecida correctamente"}
    except AuthError as exc:
        _raise_http_auth_error(exc)


@router.post(
    "/registro-empresa",
    response_model=RegistroEmpresaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nueva empresa y administrador",
    description="Permite el auto-registro público de un nuevo tenant con su cuenta administradora inicial.",
    responses={
        409: {
            "description": "Ya existe una empresa con ese NIT o slug, o el usuario/correo ya está en uso."
        },
        422: {"description": "Datos de registro inválidos."},
    },
)
async def registro_empresa(
    request: RegistroEmpresaRequest,
    session: AsyncSession = Depends(get_session),
):
    from ssas.platform.application.use_cases.provision_empresa import ProvisionEmpresa
    from ssas.platform.domain.exceptions import PlatformConflictError, PlatformError
    from ssas.platform.infrastructure.http.schemas import (
        EmpresaCreateData,
        InitialAdminData,
        ProvisionEmpresaRequest,
    )

    try:
        provision_req = ProvisionEmpresaRequest(
            empresa=EmpresaCreateData(
                nit=request.nit,
                razon_social=request.razon_social,
                nombre_comercial=request.nombre_comercial,
                slug=request.slug,
                email=request.email or request.admin_email,
                telefono=request.telefono or request.admin_telefono,
                ciudad=request.ciudad,
                color_primario=request.color_primario,
                descripcion=request.descripcion,
                portal_publico_activo=True,
            ),
            administrador=InitialAdminData(
                nombre=request.admin_nombre,
                apellido=request.admin_apellido,
                email=request.admin_email,
                username=request.admin_username,
                password=request.admin_password,
                telefono=request.admin_telefono,
            ),
            modulos=None,
        )
        empresa, admin, _ = await ProvisionEmpresa(session).execute(provision_req)

        access_token = token_service.create_access_token(
            subject=admin.id,
            empresa_id=empresa.id,
            roles=["ADMIN_EMPRESA"],
        )
        refresh_token_val, jti, expires_at = token_service.create_refresh_token(
            subject=admin.id,
            empresa_id=empresa.id,
        )
        await _token_repository(session).save_refresh_token(
            token_id=jti,
            user_id=admin.id,
            empresa_id=empresa.id,
            token_hash=token_service.fingerprint(refresh_token_val),
            expires_at=expires_at,
        )
        await session.commit()
        return RegistroEmpresaResponse(
            access_token=access_token,
            refresh_token=refresh_token_val,
            token_type="bearer",
            empresa_id=empresa.id,
            empresa_nombre=empresa.nombre_comercial or empresa.razon_social,
            empresa_slug=empresa.slug,
            usuario_id=admin.id,
            usuario_email=admin.email,
            message="Empresa registrada exitosamente",
        )
    except PlatformConflictError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (PlatformError, AuthError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        logger.exception("Error al registrar empresa")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo completar el registro de la empresa",
        ) from exc
