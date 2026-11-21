"""Cursos, lecciones e inscripciones con alcance por empresa."""

import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.capacitacion.models import (
    CursoModel,
    EmpleadoHabilidadModel,
    InscripcionModel,
    LeccionModel,
    ProgresoLeccionModel,
)
from ssas.core.security.dependencies import (
    CurrentUser,
    require_scoped_any_permission,
    require_scoped_permission,
)
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.habilidades.infrastructure.persistence.models.habilidad import HabilidadModel
from ssas.infrastructure.database.session import get_session
from ssas.personal.infrastructure.persistence.models import ContratoModel

router = APIRouter(prefix="/capacitacion", tags=["Capacitación"])
MATERIAL_DIR = Path(os.getenv("CAPACITACION_FILES_DIRECTORY", "uploads/capacitacion"))
MIME = {"application/pdf": ".pdf", "video/mp4": ".mp4", "image/png": ".png", "image/jpeg": ".jpg"}


def local_today() -> date:
    return datetime.now(ZoneInfo("America/La_Paz")).date()


def scope(user: CurrentUser, empresa_id: str | None) -> str:
    target = empresa_id if user.es_plataforma else user.empresa_id
    if not target or (empresa_id and not user.es_plataforma and empresa_id != target):
        raise HTTPException(403, "Empresa no autorizada")
    return target


async def owned(session, model, item_id: str, tenant_id: str):
    result = await session.scalar(select(model).where(model.id == item_id, model.empresa_id == tenant_id))
    if result is None:
        raise HTTPException(404, "Registro no encontrado")
    return result


def view(model):
    data = {column.name: getattr(model, column.name) for column in model.__table__.columns}
    if isinstance(model, InscripcionModel) and model.fecha_limite and model.fecha_limite < local_today() and model.estado not in ("COMPLETADO", "ABANDONADO"):
        data["estado"] = "VENCIDO"
    return data


class CursoInput(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    descripcion: str | None = None
    categoria: str | None = Field(None, max_length=100)
    duracion_horas: Decimal | None = Field(None, ge=0)
    es_obligatorio: bool = False
    imagen_url: str | None = None
    instructor: str | None = Field(None, max_length=160)
    nota_minima: Decimal = Field(70, ge=0, le=100)
    habilidad_id: UUID | None = None


class LeccionInput(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    tipo: str = Field(pattern="^(VIDEO|DOCUMENTO|MANUAL|QUIZ|ENLACE)$")
    contenido_url: str | None = None
    contenido_texto: str | None = None
    orden: int = Field(gt=0)
    duracion_minutos: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def content(self):
        if not self.contenido_url and not self.contenido_texto:
            raise ValueError("Indica contenido_url o contenido_texto")
        if self.tipo == "QUIZ":
            try:
                questions = json.loads(self.contenido_texto or "{}")["preguntas"]
                if not questions or any(not q["enunciado"] or len(q["opciones"]) < 2 or not 0 <= q["correcta"] < len(q["opciones"]) for q in questions):
                    raise ValueError("Quiz inválido")
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("El quiz requiere preguntas, opciones y correcta") from exc
        return self


class AsignacionInput(BaseModel):
    curso_id: UUID
    empleado_id: UUID | None = None
    departamento_id: UUID | None = None
    fecha_limite: date | None = None

    @model_validator(mode="after")
    def one_target(self):
        if (self.empleado_id is None) == (self.departamento_id is None):
            raise ValueError("Indica exactamente un empleado_id o departamento_id")
        if self.fecha_limite and self.fecha_limite < local_today():
            raise ValueError("La fecha límite no puede estar vencida")
        return self


class LeccionCompletadaInput(BaseModel):
    respuestas: list[int] | None = None


class CalificacionInput(BaseModel):
    calificacion: Decimal = Field(ge=0, le=100)


class HabilidadInput(BaseModel):
    empleado_id: UUID
    habilidad_id: UUID
    nivel: str | None = Field(None, max_length=30)
    adquirida_en: date | None = None
    fecha_evaluacion: datetime | None = None


MANAGE = Depends(require_scoped_permission("capacitacion:gestionar", "platform:capacitacion:gestionar"))
READ = Depends(require_scoped_any_permission(("capacitacion:ver", "capacitacion:aprender"), ("platform:capacitacion:gestionar",)))
LEARN = Depends(require_scoped_permission("capacitacion:aprender", "platform:capacitacion:gestionar"))


@router.get("/cursos")
async def cursos(empresa_id: str | None = None, user: CurrentUser = READ, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    query = select(CursoModel).where(CursoModel.empresa_id == target)
    if not await can_manage(session, user, target):
        query = query.where(CursoModel.estado == "PUBLICADO")
    items = await session.scalars(query.order_by(CursoModel.creado_en.desc()).limit(200))
    return [view(item) for item in items]


@router.post("/cursos", status_code=201)
async def crear_curso(body: CursoInput, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    if body.habilidad_id:
        await owned(session, HabilidadModel, str(body.habilidad_id), target)
    item = CursoModel(id=str(uuid4()), empresa_id=target, **body.model_dump(mode="json"))
    session.add(item)
    await session.flush()
    return view(item)


@router.get("/cursos/{curso_id}")
async def curso(curso_id: UUID, empresa_id: str | None = None, user: CurrentUser = READ, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    item = await owned(session, CursoModel, str(curso_id), target)
    if item.estado != "PUBLICADO" and not await can_manage(session, user, target):
        raise HTTPException(404, "Curso no encontrado")
    return view(item)


@router.patch("/cursos/{curso_id}")
async def editar_curso(curso_id: UUID, body: CursoInput, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    item = await owned(session, CursoModel, str(curso_id), target)
    if item.estado != "BORRADOR":
        raise HTTPException(409, "Solo se edita un borrador")
    if body.habilidad_id:
        await owned(session, HabilidadModel, str(body.habilidad_id), target)
    for key, value in body.model_dump(mode="json").items():
        setattr(item, key, value)
    await session.flush()
    return view(item)


@router.post("/cursos/{curso_id}/publicar")
async def publicar(curso_id: UUID, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    item = await owned(session, CursoModel, str(curso_id), target)
    lesson = await session.scalar(select(LeccionModel.id).where(LeccionModel.empresa_id == target, LeccionModel.curso_id == item.id).limit(1))
    if lesson is None:
        raise HTTPException(409, "Agrega al menos una lección antes de publicar")
    item.estado = "PUBLICADO"
    await session.flush()
    return view(item)


@router.delete("/cursos/{curso_id}", status_code=204)
async def borrar_curso(curso_id: UUID, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    item = await owned(session, CursoModel, str(curso_id), target)
    if item.estado != "BORRADOR" or await session.scalar(select(InscripcionModel.id).where(InscripcionModel.curso_id == item.id).limit(1)):
        raise HTTPException(409, "Solo puede eliminarse un borrador sin inscripciones")
    await session.delete(item)


@router.get("/cursos/{curso_id}/lecciones")
async def lecciones(curso_id: UUID, empresa_id: str | None = None, user: CurrentUser = READ, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    course = await owned(session, CursoModel, str(curso_id), target)
    if course.estado != "PUBLICADO" and not await can_manage(session, user, target):
        raise HTTPException(404, "Curso no encontrado")
    items = await session.scalars(select(LeccionModel).where(LeccionModel.empresa_id == target, LeccionModel.curso_id == str(curso_id)).order_by(LeccionModel.orden))
    reveal_answers = await can_manage(session, user, target)
    return [view(item) if reveal_answers else lesson_view(item) for item in items]


@router.post("/cursos/{curso_id}/lecciones", status_code=201)
async def crear_leccion(curso_id: UUID, body: LeccionInput, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    course = await owned(session, CursoModel, str(curso_id), target)
    if course.estado != "BORRADOR":
        raise HTTPException(409, "Solo se agregan lecciones a borradores")
    item = LeccionModel(id=str(uuid4()), empresa_id=target, curso_id=course.id, **body.model_dump())
    session.add(item)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "El orden ya está ocupado") from exc
    return view(item)


@router.patch("/lecciones/{leccion_id}")
async def editar_leccion(leccion_id: UUID, body: LeccionInput, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    item = await owned(session, LeccionModel, str(leccion_id), target)
    course = await owned(session, CursoModel, item.curso_id, target)
    if course.estado != "BORRADOR":
        raise HTTPException(409, "Solo se editan borradores")
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    await session.flush()
    return view(item)


@router.delete("/lecciones/{leccion_id}", status_code=204)
async def borrar_leccion(leccion_id: UUID, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    item = await owned(session, LeccionModel, str(leccion_id), target)
    course = await owned(session, CursoModel, item.curso_id, target)
    if course.estado != "BORRADOR":
        raise HTTPException(409, "Solo se editan borradores")
    await session.delete(item)


@router.post("/materiales", status_code=201)
async def subir_material(archivo: UploadFile = File(...), empresa_id: str | None = None, user: CurrentUser = MANAGE):
    target = scope(user, empresa_id)
    suffix = MIME.get(archivo.content_type or "")
    if suffix is None:
        raise HTTPException(422, "Solo PDF, MP4, PNG o JPG")
    content = await archivo.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "El archivo supera 20 MB")
    if suffix == ".pdf" and not content.startswith(b"%PDF-") or suffix == ".mp4" and b"ftyp" not in content[:16]:
        raise HTTPException(422, "Contenido del archivo inválido")
    folder = MATERIAL_DIR / target
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4()}{suffix}"
    (folder / name).write_bytes(content)
    return {"contenido_url": f"/api/v1/capacitacion/materiales/{name}"}


@router.get("/materiales/{nombre}")
async def descargar_material(nombre: str, empresa_id: str | None = None, user: CurrentUser = READ):
    if Path(nombre).name != nombre:
        raise HTTPException(404, "Archivo no encontrado")
    file = MATERIAL_DIR / scope(user, empresa_id) / nombre
    if not file.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(file)


async def can_manage(session: AsyncSession, user: CurrentUser, target: str) -> bool:
    if user.es_plataforma:
        return True
    from ssas.roles.infrastructure.persistence.repositories.authorization_repository import (
        SqlAlchemyAuthorizationRepository,
    )
    permissions = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(user.id, target)
    return "capacitacion:gestionar" in permissions


def lesson_view(item: LeccionModel) -> dict:
    data = view(item)
    if item.tipo == "QUIZ":
        quiz = json.loads(item.contenido_texto or "{}")
        for question in quiz.get("preguntas", []):
            question.pop("correcta", None)
        data["contenido_texto"] = json.dumps(quiz, ensure_ascii=False)
    return data


@router.post("/inscripciones", status_code=201)
async def asignar(body: AsignacionInput, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    course = await owned(session, CursoModel, str(body.curso_id), target)
    if course.estado != "PUBLICADO":
        raise HTTPException(409, "El curso debe estar publicado")
    if body.empleado_id:
        employee = await owned(session, EmpleadoModel, str(body.empleado_id), target)
        employees = [employee]
    else:
        employees = (await session.scalars(select(EmpleadoModel).join(ContratoModel, (ContratoModel.empleado_id == EmpleadoModel.id) & (ContratoModel.empresa_id == target)).where(EmpleadoModel.empresa_id == target, EmpleadoModel.estado == "ACTIVO", ContratoModel.departamento_id == str(body.departamento_id), ContratoModel.estado == "VIGENTE").distinct())).all()
    created = []
    for employee in employees:
        existing = await session.scalar(select(InscripcionModel.id).where(InscripcionModel.curso_id == course.id, InscripcionModel.empleado_id == employee.id))
        if existing is None:
            item = InscripcionModel(id=str(uuid4()), empresa_id=target, curso_id=course.id, empleado_id=employee.id, fecha_limite=body.fecha_limite)
            session.add(item)
            created.append(item)
    await session.flush()
    return {"inscripciones": [view(item) for item in created], "cantidad": len(created)}


async def own_enrollment(session, item_id: str, user: CurrentUser, target: str, self_service: bool):
    item = await owned(session, InscripcionModel, item_id, target)
    if self_service and not user.es_plataforma:
        employee = await session.scalar(select(EmpleadoModel.id).where(EmpleadoModel.id == item.empleado_id, EmpleadoModel.empresa_id == target, EmpleadoModel.usuario_id == user.id))
        if employee is None:
            raise HTTPException(403, "Inscripción ajena")
    return item


@router.get("/mis-cursos")
async def mis_cursos(empresa_id: str | None = None, user: CurrentUser = LEARN, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    employee = await session.scalar(select(EmpleadoModel.id).where(EmpleadoModel.empresa_id == target, EmpleadoModel.usuario_id == user.id))
    if employee is None:
        return []
    rows = (await session.execute(
        select(InscripcionModel, CursoModel.titulo, CursoModel.es_obligatorio)
        .join(CursoModel, (CursoModel.id == InscripcionModel.curso_id)
              & (CursoModel.empresa_id == InscripcionModel.empresa_id))
        .where(InscripcionModel.empresa_id == target, InscripcionModel.empleado_id == employee)
        .order_by(InscripcionModel.inscrito_en.desc())
    )).all()
    return [{**view(item), "curso_titulo": title, "curso_obligatorio": required}
            for item, title, required in rows]


@router.get("/inscripciones")
async def inscripciones(curso_id: UUID | None = None, empresa_id: str | None = None, user: CurrentUser = READ, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    query = select(InscripcionModel).where(InscripcionModel.empresa_id == target)
    if curso_id:
        query = query.where(InscripcionModel.curso_id == str(curso_id))
    items = await session.scalars(query.limit(500))
    return [view(item) for item in items]


@router.post("/inscripciones/{inscripcion_id}/lecciones/{leccion_id}/completar")
async def completar(inscripcion_id: UUID, leccion_id: UUID, body: LeccionCompletadaInput, empresa_id: str | None = None, user: CurrentUser = LEARN, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    enrollment = await own_enrollment(session, str(inscripcion_id), user, target, True)
    lesson = await owned(session, LeccionModel, str(leccion_id), target)
    if lesson.curso_id != enrollment.curso_id:
        raise HTTPException(422, "La lección no pertenece al curso")
    if enrollment.estado in ("ABANDONADO", "VENCIDO"):
        raise HTTPException(409, "Inscripción inactiva")
    if enrollment.fecha_limite and enrollment.fecha_limite < local_today() and enrollment.estado != "COMPLETADO":
        raise HTTPException(409, "La inscripción venció")
    grade = None
    if lesson.tipo == "QUIZ":
        questions = json.loads(lesson.contenido_texto or "{}")["preguntas"]
        if body.respuestas is None or len(body.respuestas) != len(questions):
            raise HTTPException(422, "Responde todas las preguntas del quiz")
        correct = sum(answer == question["correcta"] for answer, question in zip(body.respuestas, questions))
        grade = Decimal(correct * 100) / Decimal(len(questions))
    progress = await session.scalar(select(ProgresoLeccionModel).where(ProgresoLeccionModel.inscripcion_id == enrollment.id, ProgresoLeccionModel.leccion_id == lesson.id))
    if progress is None:
        progress = ProgresoLeccionModel(id=str(uuid4()), empresa_id=target, inscripcion_id=enrollment.id, leccion_id=lesson.id, calificacion=grade)
        session.add(progress)
        await session.flush()
    total = len((await session.scalars(select(LeccionModel.id).where(LeccionModel.curso_id == enrollment.curso_id, LeccionModel.empresa_id == target))).all())
    completed = len((await session.scalars(select(ProgresoLeccionModel.id).where(ProgresoLeccionModel.inscripcion_id == enrollment.id))).all())
    enrollment.progreso = Decimal(completed * 100) / Decimal(total)
    enrollment.estado = "COMPLETADO" if completed == total else "EN_CURSO"
    if completed == total:
        grades = (await session.scalars(select(ProgresoLeccionModel.calificacion).where(ProgresoLeccionModel.inscripcion_id == enrollment.id, ProgresoLeccionModel.calificacion.is_not(None)))).all()
        enrollment.calificacion = sum(grades, Decimal(0)) / Decimal(len(grades)) if grades else Decimal(100)
        course = await owned(session, CursoModel, enrollment.curso_id, target)
        enrollment.aprobado = enrollment.calificacion >= course.nota_minima
        enrollment.certificado_url = f"/api/v1/capacitacion/inscripciones/{enrollment.id}/certificado" if enrollment.aprobado else None
        if enrollment.aprobado:
            await certify_skill(session, enrollment, course, user.id)
    await session.flush()
    return view(enrollment)


@router.post("/inscripciones/{inscripcion_id}/calificar")
async def calificar(inscripcion_id: UUID, body: CalificacionInput, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    enrollment = await owned(session, InscripcionModel, str(inscripcion_id), target)
    if enrollment.progreso != 100:
        raise HTTPException(409, "Completa las lecciones antes de calificar")
    course = await owned(session, CursoModel, enrollment.curso_id, target)
    enrollment.calificacion = body.calificacion
    enrollment.aprobado = body.calificacion >= course.nota_minima
    enrollment.certificado_url = f"/api/v1/capacitacion/inscripciones/{enrollment.id}/certificado" if enrollment.aprobado else None
    if enrollment.aprobado:
        await certify_skill(session, enrollment, course, user.id)
    await session.flush()
    return view(enrollment)


@router.get("/inscripciones/{inscripcion_id}/certificado")
async def certificado(inscripcion_id: UUID, empresa_id: str | None = None, user: CurrentUser = READ, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    item = await owned(session, InscripcionModel, str(inscripcion_id), target)
    if not item.aprobado:
        raise HTTPException(409, "Curso sin aprobación")
    if not user.es_plataforma:
        employee = await session.scalar(select(EmpleadoModel).where(EmpleadoModel.id == item.empleado_id, EmpleadoModel.empresa_id == target))
        if employee is None or employee.usuario_id != user.id:
            # Un gestor puede consultar el certificado de su propia empresa.
            from ssas.roles.infrastructure.persistence.repositories.authorization_repository import (
                SqlAlchemyAuthorizationRepository,
            )
            permissions = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(user.id, target)
            if "capacitacion:gestionar" not in permissions:
                raise HTTPException(403, "Certificado ajeno")
    course = await owned(session, CursoModel, item.curso_id, target)
    employee = await owned(session, EmpleadoModel, item.empleado_id, target)
    buffer = BytesIO()
    pdf = Canvas(buffer)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawCentredString(300, 720, "CERTIFICADO DE CAPACITACION")
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(300, 655, f"{employee.nombres} {employee.apellido_paterno}")
    pdf.drawCentredString(300, 620, f"Curso: {course.titulo}")
    pdf.drawCentredString(300, 585, f"Calificacion: {item.calificacion}/100")
    pdf.drawCentredString(300, 550, f"Inscripcion: {item.id}")
    pdf.save()
    return Response(buffer.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="certificado-{item.id}.pdf"'})


@router.post("/empleado-habilidades", status_code=201)
async def registrar_habilidad(body: HabilidadInput, empresa_id: str | None = None, user: CurrentUser = MANAGE, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    await owned(session, EmpleadoModel, str(body.empleado_id), target)
    await owned(session, HabilidadModel, str(body.habilidad_id), target)
    item = EmpleadoHabilidadModel(id=str(uuid4()), empresa_id=target, empleado_id=str(body.empleado_id), habilidad_id=str(body.habilidad_id), nivel=body.nivel, adquirida_en=body.adquirida_en, fecha_evaluacion=body.fecha_evaluacion, certificado_por=user.id)
    session.add(item)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "Habilidad ya registrada") from exc
    return view(item)


async def certify_skill(session: AsyncSession, enrollment: InscripcionModel, course: CursoModel, certifier_id: str):
    if not course.habilidad_id:
        return
    existing = await session.scalar(select(EmpleadoHabilidadModel).where(
        EmpleadoHabilidadModel.empresa_id == enrollment.empresa_id,
        EmpleadoHabilidadModel.empleado_id == enrollment.empleado_id,
        EmpleadoHabilidadModel.habilidad_id == course.habilidad_id,
    ))
    if existing is None:
        existing = EmpleadoHabilidadModel(id=str(uuid4()), empresa_id=enrollment.empresa_id,
            empleado_id=enrollment.empleado_id, habilidad_id=course.habilidad_id)
        session.add(existing)
    existing.nivel = "CERTIFICADO"
    existing.adquirida_en = local_today()
    existing.fecha_evaluacion = datetime.now(UTC)
    existing.certificado_por = certifier_id
    existing.curso_id = course.id


async def skill_profile(session: AsyncSession, target: str, employee_id: str):
    rows = (await session.execute(
        select(EmpleadoHabilidadModel, HabilidadModel.nombre, CursoModel.titulo)
        .join(HabilidadModel, HabilidadModel.id == EmpleadoHabilidadModel.habilidad_id)
        .outerjoin(CursoModel, CursoModel.id == EmpleadoHabilidadModel.curso_id)
        .where(EmpleadoHabilidadModel.empresa_id == target,
               EmpleadoHabilidadModel.empleado_id == employee_id)
        .order_by(HabilidadModel.nombre)
    )).all()
    return [{**view(item), "habilidad_nombre": name, "curso_titulo": course_title}
            for item, name, course_title in rows]


@router.get("/mis-habilidades")
async def mis_habilidades(empresa_id: str | None = None, user: CurrentUser = LEARN,
                         session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    employee = await session.scalar(select(EmpleadoModel.id).where(
        EmpleadoModel.empresa_id == target, EmpleadoModel.usuario_id == user.id))
    return await skill_profile(session, target, employee) if employee else []


@router.get("/empleados/{empleado_id}/habilidades")
async def habilidades_empleado(empleado_id: UUID, empresa_id: str | None = None,
                               user: CurrentUser = READ, session: AsyncSession = Depends(get_session)):
    target = scope(user, empresa_id)
    employee = await owned(session, EmpleadoModel, str(empleado_id), target)
    if not await can_manage(session, user, target) and employee.usuario_id != user.id:
        raise HTTPException(403, "Perfil ajeno")
    return await skill_profile(session, target, employee.id)
