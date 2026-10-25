import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.domain.password_policy import validate_password
from ssas.auth.infrastructure.persistence.models.email_verification_token import (
    EmailVerificationTokenModel,
)
from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.auth.infrastructure.security.password_hasher import Argon2PasswordHasher
from ssas.config.settings import settings
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.empresas.infrastructure.persistence.models.suscripcion import (
    PlanSuscripcionModel,
    SuscripcionModel,
)
from ssas.modulos.infrastructure.persistence.models.empresa_modulo import EmpresaModuloModel
from ssas.modulos.infrastructure.persistence.models.modulo import ModuloModel
from ssas.personal.application.payroll import SEED_RULES
from ssas.personal.infrastructure.persistence.models import (
    EstructuraSalarialModel,
    ReglaSalarialModel,
    TipoAusenciaModel,
)
from ssas.platform.domain.exceptions import (
    PlatformConflictError,
    RolBasePermisoDesconocidoError,
)
from ssas.platform.infrastructure.persistence.repositories.platform_repository import (
    PlatformRepository,
)
from ssas.postulaciones.infrastructure.persistence.models.etapa_reclutamiento import (
    EtapaReclutamientoModel,
)
from ssas.postulaciones.infrastructure.persistence.models.motivo_rechazo import (
    MotivoRechazoModel,
)
from ssas.roles.infrastructure.persistence.models.permission import PermissionModel
from ssas.roles.infrastructure.persistence.models.role import RoleModel
from ssas.roles.infrastructure.persistence.models.role_permission import rol_permiso_table
from ssas.roles.infrastructure.persistence.models.user_role import usuario_rol_table
from ssas.suscripciones.infrastructure.persistence.models.saas import PlanModuloModel

ROLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...] | None], ...] = (
    ("ADMIN_EMPRESA", "Administrador de Empresa", None),
    (
        "RRHH",
        "Recursos Humanos",
        (
            "usuarios:ver",
            "usuarios:crear",
            "usuarios:editar",
            "bitacora:ver",
            "vacantes:ver",
            "habilidades:ver",
            "postulantes:ver",
            "postulantes:gestionar",
            "postulaciones:ver",
            "postulaciones:gestionar",
            "entrevistas:ver",
            "entrevistas:gestionar",
            "entrevistas:registrar_resultado",
            "evaluaciones:ver",
            "evaluaciones:gestionar",
            "postulaciones:analizar_cv",
            "postulaciones:contratar",
            "empleados:ver",
            "personal:ver",
            "personal:gestionar",
            "personal:mi",
            "asistencia:ver",
            "asistencia:marcar",
            "asistencia:solicitar_ajuste",
            "asistencia:aprobar_ajuste",
            "asistencia:autorizar_extra",
            "asistencia:mi",
            "ausencias:gestionar",
            "ausencias:aprobar",
            "ausencias:solicitar",
            "ausencias:mi",
            "nomina:ver",
            "nomina:gestionar",
            "boletas:ver",
            "boletas:mi",
        ),
    ),
    (
        "RECLUTADOR",
        "Reclutador",
        (
            "vacantes:ver",
            "vacantes:crear",
            "vacantes:editar",
            "vacantes:publicar",
            "habilidades:ver",
            "postulantes:ver",
            "postulaciones:ver",
            "postulaciones:gestionar",
            "entrevistas:ver",
            "entrevistas:gestionar",
            "entrevistas:registrar_resultado",
            "evaluaciones:ver",
            "evaluaciones:gestionar",
            "postulaciones:analizar_cv",
            "postulantes:gestionar",
        ),
    ),
    (
        "JEFE_AREA",
        "Jefe de Área",
        (
            "personal:mi",
            "personal:ver_equipo",
            "asistencia:ver_equipo",
            "asistencia:mi",
            "asistencia:marcar",
            "asistencia:solicitar_ajuste",
            "asistencia:aprobar_ajuste",
            "ausencias:aprobar",
            "ausencias:solicitar",
            "ausencias:mi",
            "boletas:mi",
            "departamentos:ver",
            "cargos:ver",
            "vacantes:ver",
            "postulaciones:ver",
            "entrevistas:ver",
            "entrevistas:registrar_resultado",
            "evaluaciones:ver",
            "evaluaciones:gestionar",
        ),
    ),
    (
        "EMPLEADO",
        "Empleado",
        (
            "personal:mi",
            "asistencia:marcar",
            "asistencia:solicitar_ajuste",
            "asistencia:mi",
            "ausencias:solicitar",
            "ausencias:mi",
            "boletas:mi",
        ),
    ),
)


PREFIJO_PLATAFORMA = "platform:"


class ProvisionEmpresa:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = PlatformRepository(session)
        self.password_hasher = Argon2PasswordHasher()

    async def _habilitar_modulos(self, empresa_id: str, solicitados: list[str] | None) -> None:
        """Deja registrada la habilitación de los módulos contratables.

        Los módulos núcleo no se registran: están siempre disponibles. Sin lista
        explícita se habilitan todos, que es lo que espera quien da de alta una
        empresa sin pensar todavía en el alcance funcional.
        """
        catalogo_completo = (
            (await self.session.execute(select(ModuloModel).where(ModuloModel.activo.is_(True))))
            .scalars()
            .all()
        )
        if not catalogo_completo:
            return
        codigos = {modulo.codigo for modulo in catalogo_completo}
        if solicitados is not None:
            desconocidos = sorted(set(solicitados) - codigos)
            if desconocidos:
                raise PlatformConflictError(f"Módulos inexistentes: {', '.join(desconocidos)}")
        ahora = datetime.now(UTC)
        for modulo in catalogo_completo:
            if modulo.es_core:
                continue
            habilitado = solicitados is None or modulo.codigo in solicitados
            self.session.add(
                EmpresaModuloModel(
                    empresa_id=empresa_id,
                    modulo_id=modulo.id,
                    habilitado=habilitado,
                    fecha_habilitacion=ahora if habilitado else None,
                )
            )
        await self.session.flush()

    async def _crear_etapas_y_motivos_iniciales(self, empresa_id: str) -> None:
        """Crea las etapas iniciales de reclutamiento y motivos de rechazo para el tenant."""
        etapas_base = [
            ("Postulado", 1, "#64748b", True, False, False),
            ("Preseleccionado", 2, "#2563eb", False, False, False),
            ("Entrevista", 3, "#7c3aed", False, False, False),
            ("Oferta", 4, "#f59e0b", False, False, False),
            ("Contratado", 5, "#16a34a", False, True, False),
            ("Descartado", 6, "#dc2626", False, False, True),
        ]
        for nombre, orden, color, es_ini, es_con, es_rec in etapas_base:
            self.session.add(
                EtapaReclutamientoModel(
                    empresa_id=empresa_id,
                    nombre=nombre,
                    orden=orden,
                    color=color,
                    es_inicial=es_ini,
                    es_contratado=es_con,
                    es_rechazado=es_rec,
                )
            )
        motivos_base = [
            "No cumple perfil técnico",
            "Expectativa salarial fuera de rango",
            "No se presentó a la entrevista",
            "Desistimiento del postulante",
            "Otro",
        ]
        for nombre in motivos_base:
            self.session.add(
                MotivoRechazoModel(
                    empresa_id=empresa_id,
                    nombre=nombre,
                    activo=True,
                )
            )
        await self.session.flush()

    @staticmethod
    def _resolver_permisos(
        rol: str,
        codigos: tuple[str, ...],
        permisos_por_codigo: dict[str, PermissionModel],
    ) -> list[PermissionModel]:
        """Traduce los códigos de un rol base a filas del catálogo de permisos.

        Falla en voz alta si algún código no existe: descartarlo en silencio deja el
        rol sin permisos y el error solo se descubre en producción.
        """
        desconocidos = sorted(set(codigos) - set(permisos_por_codigo))
        if desconocidos:
            raise RolBasePermisoDesconocidoError(
                f"El rol base '{rol}' referencia permisos inexistentes en el catálogo: "
                f"{', '.join(desconocidos)}"
            )
        return [permisos_por_codigo[codigo] for codigo in codigos]

    async def execute(self, request) -> tuple[EmpresaModel, UserModel, str]:
        empresa_data = request.empresa.model_dump()
        empresa_data["slug"] = empresa_data["slug"].strip().lower()
        if empresa_data.get("nit"):
            empresa_data["nit"] = empresa_data["nit"].strip()
        if await self.repository.get_empresa_by_unique(
            empresa_data.get("nit"), empresa_data["slug"]
        ):
            raise PlatformConflictError("Ya existe una empresa con ese NIT o slug")
        admin_data = request.administrador.model_dump()
        email = str(admin_data["email"]).strip().lower()
        username = admin_data["username"].strip().lower()
        validate_password(admin_data["password"], username, email)

        empresa = EmpresaModel(**empresa_data, activo=True)
        self.session.add(empresa)
        await self.session.flush()

        plan_inicial = await self.session.scalar(
            select(PlanSuscripcionModel)
            .where(PlanSuscripcionModel.activo.is_(True))
            .order_by(PlanSuscripcionModel.precio_mensual, PlanSuscripcionModel.nombre)
            .limit(1)
        )
        if plan_inicial is None:
            raise PlatformConflictError(
                "No existe un plan SaaS activo para aprovisionar la empresa"
            )
        self.session.add(
            SuscripcionModel(
                empresa_id=empresa.id,
                plan_id=plan_inicial.id,
                estado="ACTIVA",
                fecha_inicio=datetime.now(UTC).date(),
            )
        )
        modulos_del_plan = list(
            (
                await self.session.execute(
                    select(ModuloModel.codigo)
                    .join(PlanModuloModel, PlanModuloModel.modulo_id == ModuloModel.id)
                    .where(PlanModuloModel.plan_id == plan_inicial.id)
                )
            )
            .scalars()
            .all()
        )
        await self._habilitar_modulos(empresa.id, modulos_del_plan)
        await self._crear_etapas_y_motivos_iniciales(empresa.id)
        for code, name, paid, vacation, document in (
            ("VACACION", "Vacacion", True, True, False),
            ("PERMISO", "Permiso", True, False, False),
            ("LICENCIA_MEDICA", "Licencia medica", True, False, True),
            ("SIN_GOCE", "Sin goce", False, False, False),
        ):
            self.session.add(
                TipoAusenciaModel(
                    empresa_id=empresa.id,
                    codigo=code,
                    nombre=name,
                    es_remunerado=paid,
                    descuenta_vacacion=vacation,
                    requiere_documento=document,
                )
            )
        structure = EstructuraSalarialModel(empresa_id=empresa.id, nombre="Nomina general")
        self.session.add(structure)
        await self.session.flush()
        for code, name, kind, sequence, calculation, basis, parameter in SEED_RULES:
            self.session.add(
                ReglaSalarialModel(
                    empresa_id=empresa.id,
                    estructura_id=structure.id,
                    codigo=code,
                    nombre=name,
                    tipo=kind,
                    secuencia=sequence,
                    tipo_calculo=calculation,
                    base_calculo=basis,
                    parametro_codigo=parameter,
                )
            )
        # Un rol de empresa NUNCA puede recibir permisos de plataforma: son operaciones
        # del proveedor SaaS (crear empresas y gestionar administradores globales).
        # Sin este filtro, ADMIN_EMPRESA —que se define con "todos los permisos"— se
        # llevaría también los platform:*.
        permissions = [
            permiso
            for permiso in (await self.session.execute(select(PermissionModel))).scalars().all()
            if not permiso.name.startswith(PREFIJO_PLATAFORMA)
        ]
        permission_by_code = {permission.name: permission for permission in permissions}
        roles: dict[str, RoleModel] = {}
        for code, name, permission_codes in ROLE_DEFINITIONS:
            role = RoleModel(
                empresa_id=empresa.id, name=name, codigo=code, es_base=True, is_active=True
            )
            self.session.add(role)
            await self.session.flush()
            roles[code] = role
            selected = (
                permissions
                if permission_codes is None
                else self._resolver_permisos(code, permission_codes, permission_by_code)
            )
            if selected:
                await self.session.execute(
                    rol_permiso_table.insert(),
                    [{"rol_id": role.id, "permiso_id": permission.id} for permission in selected],
                )

        admin = UserModel(
            empresa_id=empresa.id,
            name=admin_data["nombre"].strip(),
            apellido=admin_data["apellido"].strip(),
            email=email,
            username=username,
            hashed_password=self.password_hasher.hash(admin_data["password"]),
            telefono=admin_data.get("telefono"),
            is_active=True,
            email_verified=True,
            debe_cambiar_password=False,
        )
        self.session.add(admin)
        await self.session.flush()
        await self.session.execute(
            usuario_rol_table.insert().values(usuario_id=admin.id, rol_id=roles["ADMIN_EMPRESA"].id)
        )

        raw_token = secrets.token_urlsafe(32)
        from ssas.core.security.jwt import JWTService

        self.session.add(
            EmailVerificationTokenModel(
                id=str(uuid4()),
                empresa_id=empresa.id,
                user_id=admin.id,
                token_hash=JWTService().fingerprint(raw_token),
                expires_at=datetime.now(UTC)
                + timedelta(minutes=settings.app_email_verification_expire_minutes),
            )
        )
        await self.session.flush()
        empresa = await self.repository.get_empresa(empresa.id)
        return empresa, admin, raw_token
