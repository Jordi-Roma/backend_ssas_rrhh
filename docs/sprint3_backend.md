# Sprint 3 backend: estado de implementacion

Este cambio agrega el esquema de contratos, documentos de legajo, asistencia,
ausencias y nomina en `20261024_0011_personal_nomina`. Las rutas estan en
`/api/v1/personal` y `/api/v1/nomina`; su contrato se publica en `/docs` y
`/openapi.json`. Los permisos se asignan por empresa y se incluyen los datos
nuevos en el respaldo aislado de cada empresa.

## Rutas disponibles

- `GET/POST /personal/empleados/{id}/contratos`, `GET /personal/mi/contratos`.
- `GET/POST /personal/empleados/{id}/documentos`, descarga privada, y
  `GET/POST /personal/mi/documentos` con carga de comprobante medico y descarga
  propia. Maximo 10 MB;
  PDF/JPEG/PNG. Configurar `EMPLOYEE_FILES_DIRECTORY` en un volumen persistente.
- `POST /personal/mi/asistencia/entrada`, `POST /personal/mi/asistencia/salida`,
  `GET /personal/mi/asistencia`. El contrato define hora programada, horas
  de jornada y descanso; el fichaje informa retraso y horas extra brutas.
- `POST /personal/mi/asistencia/correcciones`: el empleado propone nuevos
  horarios para un fichaje existente o un dia omitido (sin `asistencia_id`),
  siempre con motivo. `POST /personal/asistencia/
  correcciones/{id}/decision`: solo su jefe directo vigente acepta o rechaza.
  Una correccion aprobada recalcula jornada, retraso y horas extra, borra las
  coordenadas antiguas y queda auditada. No se modifica un mes ya calculado.
- `POST /personal/mi/asistencia/horas-extra`: el empleado solicita hasta las
  horas extra fichadas. `/personal/asistencia/horas-extra/{id}/jefe` exige
  confirmacion del jefe; `/rrhh` requiere otra persona autorizada, importe
  positivo y referencia de calculo. Solo el importe final aprobado se incluye
  en la boleta. Las solicitudes pendientes bloquean el calculo del mes; las
  rechazadas no se pagan. Hay bandejas `GET /mi/equipo/asistencia/ajustes` y
  `GET /asistencia/horas-extra/pendientes-rrhh`.
- `GET /personal/tipos-ausencia`, `POST/GET /personal/mi/ausencias`,
  `POST /personal/ausencias/{id}/decision` y asignacion de saldo de vacaciones.
  La solicitud registra el rango calendario; la aprobacion de vacaciones exige
  `dias_habiles_vacacion` revisados antes de descontar el saldo. Una licencia
  medica exige `documento_id` del legajo de ese mismo empleado.
- `GET/POST /nomina/periodos`, calculo y aprobacion, consulta de estructura,
  alta de reglas, registro de datos de la planilla tributaria por empleado y
  periodo, consulta de boletas y detalle de la boleta propia.
- `POST /nomina/salario-minimo`: plataforma registra monto, vigencia y norma.
  `PUT /nomina/periodos/{id}/rc-iva/datos` recibe importes F110 y saldos
  verificados; el cierre calcula retencion y saldo siguiente. El endpoint
  historico `/rc-iva` permanece para registrar una retencion externa revisada.
  El calculo automatico aplica dos SMN como minimo no imponible y el 13% de
  un SMN como credito desde mayo de 2025, mas F110, saldo anterior actualizado
  y credito SIETE-RG. Referencia oficial:
  https://siatinfo.impuestos.gob.bo/index.php/planilla-tributaria .
  El SMN debe cargarse por periodo con norma; la pizarra oficial indica
  Bs 3300 desde enero de 2026:
  https://www.impuestos.gob.bo/index.php/pizarra-tributaria/ .
- `GET/POST /nomina/parametros-legales`: exclusivamente plataforma; tasas
  globales con vigencia no superpuesta y referencia de norma legal.
- `PUT /nomina/periodos/{id}/haber-proporcional`: RRHH registra dias pagados,
  haber basico pagado y referencia del calculo revisado para ingresos, salidas
  o ausencias sin goce cuando se necesita una correccion manual. Sin registro,
  el cierre calcula y audita automaticamente los dias pagables y el haber.
- `GET /nomina/periodos/{id}/haber-proporcional/sugerencia?empleado_id=...`:
  previsualiza dias y haber usando dias calendario reales del mes. Ausencias pendientes bloquean el
  calculo de la nomina. El ejemplo completo ficticio esta en
  `docs/nomina_ejemplo_ficticio.md`.
- En la aprobacion RRHH de horas extra, `calculo_automatico=true` y
  `dia_no_feriado_confirmado=true` calculan el importe diurno ordinario con
  salario mensual / (30 * horas de jornada) * horas autorizadas * 2.
  Fichajes nocturnos, entre dias o dominicales quedan fuera de este modo;
  feriados deben ser descartados por RRHH. Los casos especiales conservan
  importe y referencia manuales auditados.

## Bloqueos antes de produccion

No activar nomina para pagos reales. El calculo rechaza estructuras sin todos
los conceptos legales. RC-IVA se calcula automaticamente desde mayo de 2025
si se registraron salario minimo vigente y los datos F110/saldos certificados;
el sistema no consulta ni presenta F110 al SIN. El prorrateo automatico usa
dias calendario reales, incluyendo febrero y meses de 31 dias. Esta es una
politica de producto que requiere aprobacion del responsable de nomina: el
instructivo OVT indica dias pagados y haber basico, pero no prescribe un
divisor universal para todos los casos. Sin planillas aprobadas no se puede
validar la politica de calculo de la empresa.
Los ejemplos publicos de campos del instructivo OVT-T02 del Ministerio de
Trabajo (30 dias pagados y Bs 6000.50 de haber basico) se usan en una prueba
de formato y aritmetica basica. Son ejemplos independientes, no una boleta
completa ni una regla oficial de prorrateo:
https://ovt.mintrabajo.gob.bo/ws/manuales?nombre=OVTDJ-T02 .
Los porcentajes AFP, aportes solidarios y
patronales deben cargarse por el administrador global en los parametros
legales, con vigencia y norma verificadas. No se sembraron tasas supuestas.
El Aporte Nacional Solidario (ANS) se liquida como descuento separado del
solidario ordinario, sobre la diferencia positiva de cada umbral: 1,15% sobre
Bs 13.000, 5,74% sobre Bs 25.000 y 11,48% sobre Bs 35.000. Los importes se
suman y se redondean al centavo. Solo se admite desde octubre de 2024;
periodos anteriores quedan bloqueados hasta incorporar su escala historica.
Fuente: Ley 1582 publicada por la Gestora Publica,
https://gestora.bo/archivos/bajar?id=5095 . El mes completo se registra
con 30 dias convencionales en la boleta; no equivale a asistencia verificada.
La hora extra diurna ordinaria usa recargo de 100%, conforme al art. 55 de
la Ley General del Trabajo. El divisor de 30 dias es politica de calculo,
no una regla verificada para todos los sectores. Feriados, horas nocturnas,
turnos entre dias y otras incidencias requieren tratamiento especial y no
pueden usar el modo automatico.
Fuente: https://mintrabajo.gob.bo/wp-content/uploads/2025/09/rm-229-20pdf.pdf .
Fichajes incompletos y ausencias pendientes siguen bloqueando el cierre.

Antes de desplegar: cotejar calculo tributario y reglas bolivianas vigentes
con planillas reales aprobadas, aprobar la politica de prorrateo y valor
horario, agregar pruebas de
integracion con PostgreSQL, casos multiempresa y respaldo
con documentos. Resguardar la base antes de aplicar Alembic. Los archivos del
legajo deben residir en el mismo volumen persistente del backend; el servicio
Cron no necesita ese volumen porque no sirve documentos.

No se modifico ninguna base ni entorno de Railway en esta iteracion.
