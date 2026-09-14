from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base declarativa compartida para todos los modelos ORM."""


def import_all_models() -> None:
    """Carga los modelos ORM para registrar relaciones y metadata en una Base única."""
    import ssas.auth.infrastructure.persistence.models.email_verification_token
    import ssas.auth.infrastructure.persistence.models.password_reset_token
    import ssas.auth.infrastructure.persistence.models.refresh_token
    import ssas.auth.infrastructure.persistence.models.user
    import ssas.bitacora.infrastructure.persistence.models.audit_log
    import ssas.cargos.infrastructure.persistence.models.cargo
    import ssas.departamentos.infrastructure.persistence.models.departamento
    import ssas.empresas.infrastructure.persistence.models.empresa
    import ssas.empresas.infrastructure.persistence.models.suscripcion
    import ssas.habilidades.infrastructure.persistence.models.habilidad
    import ssas.modulos.infrastructure.persistence.models.empresa_modulo
    import ssas.modulos.infrastructure.persistence.models.modulo
    import ssas.parametros_legales.infrastructure.persistence.models.parametro_legal
    import ssas.postulaciones.infrastructure.persistence.models.etapa_reclutamiento
    import ssas.postulaciones.infrastructure.persistence.models.motivo_rechazo
    import ssas.postulaciones.infrastructure.persistence.models.postulacion
    import ssas.postulaciones.infrastructure.persistence.models.postulacion_nota
    import ssas.postulantes.infrastructure.persistence.models.postulante

    # platform ya no define modelos propios: sus administradores son filas de
    # 'usuario' con empresa_id NULL y sus eventos filas de 'bitacora'.
    import ssas.roles.infrastructure.persistence.models.permission
    import ssas.roles.infrastructure.persistence.models.role
    import ssas.roles.infrastructure.persistence.models.role_permission
    import ssas.roles.infrastructure.persistence.models.user_role
    import ssas.vacantes.infrastructure.persistence.models.vacante
    import ssas.vacantes.infrastructure.persistence.models.vacante_habilidad  # noqa: F401
