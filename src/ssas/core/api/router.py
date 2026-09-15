from fastapi import APIRouter

from ssas.auth.infrastructure.http.router import router as auth_router
from ssas.bitacora.infrastructure.http.router import router as bitacora_router
from ssas.cargos.infrastructure.http.router import router as cargos_router
from ssas.dashboard.infrastructure.http.router import router as dashboard_router
from ssas.departamentos.infrastructure.http.router import router as departamentos_router
from ssas.habilidades.infrastructure.http.router import router as habilidades_router
from ssas.modulos.infrastructure.http.router import (
	empresa_router as modulos_empresa_router,
)
from ssas.modulos.infrastructure.http.router import (
	router as modulos_router,
)
from ssas.parametros_legales.infrastructure.http.router import (
	router as parametros_legales_router,
)
from ssas.platform.infrastructure.http.router import router as platform_router
from ssas.postulaciones.infrastructure.http.router import router as postulaciones_router
from ssas.postulaciones.infrastructure.http.tablero_router import router as tablero_router
from ssas.postulantes.infrastructure.http.router import router as postulantes_router
from ssas.reportes.infrastructure.http.router import router as reportes_router
from ssas.roles.infrastructure.http.router import (
	permisos_router,
)
from ssas.roles.infrastructure.http.router import (
	router as roles_router,
)
from ssas.usuarios.infrastructure.http.router import router as usuarios_router
from ssas.vacantes.infrastructure.http.router import (
	public_router as vacantes_public_router,
)
from ssas.vacantes.infrastructure.http.router import (
	router as vacantes_router,
)

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(bitacora_router)
api_router.include_router(departamentos_router)
api_router.include_router(habilidades_router)
api_router.include_router(cargos_router)
api_router.include_router(dashboard_router)
api_router.include_router(modulos_router)
api_router.include_router(modulos_empresa_router)
api_router.include_router(platform_router)
api_router.include_router(parametros_legales_router)
api_router.include_router(postulaciones_router)
api_router.include_router(postulantes_router)
api_router.include_router(tablero_router)
api_router.include_router(roles_router)
api_router.include_router(reportes_router)
api_router.include_router(permisos_router)
api_router.include_router(usuarios_router)
api_router.include_router(vacantes_router)
api_router.include_router(vacantes_public_router)
