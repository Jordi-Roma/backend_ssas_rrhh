from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ssas.config.settings import settings
from ssas.core.api.openapi import (
    CONFIGURACION_DESCRIPTION,
    TAG_AUDIT,
    TAG_AUTH,
    TAG_CARGOS,
    TAG_COMPANIES,
    TAG_CONFIGURACION,
    TAG_DASHBOARD,
    TAG_DEPARTAMENTOS,
    TAG_MODULOS,
    TAG_PORTAL_PUBLICO,
    TAG_POSTULACIONES,
    TAG_REPORTES,
    TAG_ROLES,
    TAG_STATUS,
    TAG_USERS,
    TAG_VACANTES,
)
from ssas.core.api.router import api_router
from ssas.core.tenancy.middleware import EmpresaContextMiddleware
from ssas.infrastructure.database.session import dispose_engine

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


app = FastAPI(
    title="SSAS RRHH API",
    description=(
        "Backend multiempresa para la administración de recursos humanos.\n\n"
        "## Alcance de seguridad\n"
        "- **Plataforma:** una cuenta sin empresa administra recursos globales y puede "
        "seleccionar una empresa cuando el endpoint lo permita.\n"
        "- **Empresa:** cada usuario queda limitado al `empresa_id` incluido en su token.\n"
        "- Las operaciones protegidas requieren `Authorization: Bearer <access_token>`."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {
            "name": TAG_AUTH,
            "description": "Inicio y cierre de sesión, tokens, contraseñas y correo.",
        },
        {
            "name": TAG_USERS,
            "description": "Administración de usuarios globales y usuarios por empresa.",
        },
        {
            "name": TAG_COMPANIES,
            "description": "Aprovisionamiento, consulta y estado de las empresas.",
        },
        {
            "name": TAG_ROLES,
            "description": "Roles por alcance y asignación de permisos RBAC.",
        },
        {
            "name": TAG_AUDIT,
            "description": "Consulta de eventos registrados por módulo, usuario y empresa.",
        },
        {
            "name": TAG_DEPARTAMENTOS,
            "description": "CRUD de departamentos limitado por empresa autenticada.",
        },
        {
            "name": TAG_CARGOS,
            "description": "CRUD de cargos limitado por empresa y opcionalmente por departamento.",
        },
        {
            "name": TAG_VACANTES,
            "description": "Gestión de vacantes y su publicación durante el ciclo de reclutamiento.",
        },
        {
            "name": TAG_PORTAL_PUBLICO,
            "description": "Vacantes públicas y postulación externa con hoja de vida.",
        },
        {
            "name": TAG_POSTULACIONES,
            "description": "Seguimiento y gestión de postulaciones del proceso de reclutamiento.",
        },
        {
            "name": TAG_MODULOS,
            "description": (
                "Catálogo de módulos y habilitación por empresa. Un permiso de un módulo "
                "no habilitado no surte efecto, aunque el rol lo tenga asignado."
            ),
        },
        {
            "name": TAG_DASHBOARD,
            "description": "Resumen agregado de la pantalla de inicio según el alcance.",
        },
        {
            "name": TAG_REPORTES,
            "description": "Constructor, vista previa y exportación segura de reportes.",
        },
        {
            "name": TAG_CONFIGURACION,
            "description": CONFIGURACION_DESCRIPTION,
        },
        {
            "name": TAG_STATUS,
            "description": "Estado operativo de la API.",
        },
    ],
    license_info={"name": "MIT", "identifier": "MIT"},
)
app.add_middleware(EmpresaContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=API_V1_PREFIX)


@app.get("/", include_in_schema=False)
async def read_root() -> dict[str, str]:
    return {"message": "Backend SSAS RRHH"}


@app.get(
    "/health",
    tags=[TAG_STATUS],
    summary="Verificar estado del servicio",
    description="Endpoint público usado para verificar que la API está levantada.",
    responses={200: {"description": "La API está disponible."}},
)
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
