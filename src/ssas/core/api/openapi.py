"""Convenciones compartidas para la documentación OpenAPI."""

TAG_AUTH = "Autenticación"
TAG_USERS = "Usuarios"
TAG_COMPANIES = "Empresas"
TAG_ROLES = "Roles y permisos"
TAG_AUDIT = "Bitácora"
TAG_DEPARTAMENTOS = "Departamentos"
TAG_CARGOS = "Cargos"
TAG_VACANTES = "Vacantes"
TAG_PORTAL_PUBLICO = "Portal público"
TAG_POSTULACIONES = "Postulaciones"
TAG_MODULOS = "Módulos"
TAG_DASHBOARD = "Dashboard"
TAG_STATUS = "Estado"
TAG_CONFIGURACION = "Configuración"
TAG_REPORTES = "Reportes"
TAG_RESPALDOS = "Backup / Restore"
TAG_SUSCRIPCIONES = "Planes y suscripciones"

CONFIGURACION_DESCRIPTION = (
    "Parámetros operativos y parámetros legales de la empresa: periodos de vigencia con "
    "validez histórica, sin permitir fechas superpuestas."
)

EMPRESA_SCOPE_DESCRIPTION = (
    "Identificador de empresa. Los administradores de plataforma pueden indicarlo para "
    "seleccionar el alcance; los usuarios empresariales quedan limitados a su propia empresa."
)

AUTHENTICATED_RESPONSES = {
    401: {"description": "Token de acceso ausente, inválido o vencido."},
    403: {
        "description": (
            "El usuario no tiene el permiso requerido, intenta operar fuera de su empresa "
            "o debe cambiar primero su contraseña."
        )
    },
    503: {"description": "El servicio o una dependencia externa no está disponible."},
}
