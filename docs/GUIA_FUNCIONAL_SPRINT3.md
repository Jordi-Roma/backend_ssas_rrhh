# Guía de uso de las funciones del Sprint 3

Esta guía explica las funciones de **Personal y Nómina** implementadas en el backend y las pantallas disponibles en la aplicación web. Incluye también la configuración del horario de respaldos por plan, incorporada después del trabajo inicial del sprint. El acceso a cada pantalla o acción depende de la empresa, el rol y los permisos efectivos del usuario.

## 1. Antes de comenzar

1. Iniciá sesión con una cuenta de la empresa. Si sos administrador global, seleccioná primero la empresa con la que vas a trabajar.
2. Verificá que estén cargados los empleados, sus cargos y departamentos. Para calcular nómina se necesitan contratos y una estructura salarial válida.
3. Si una opción no aparece, revisá los permisos del usuario y el plan de la empresa. Un menú visible no garantiza que todas sus acciones estén autorizadas.

## 2. Legajo y contratos

**Web → Personal → Ficha de empleado.** Seleccioná un empleado para consultar sus datos, contratos y documentos. Los documentos del legajo se cargan en PDF, JPG o PNG, con un máximo de 10 MB por archivo. Los empleados pueden consultar sus propios contratos y documentos desde la API según sus permisos.

**Web → Personal → Contratos.** Seleccioná al empleado y revisá el contrato vigente y la línea de tiempo. Para registrar un cambio de cargo, salario o condiciones, usá **Nueva versión**. El cambio crea una nueva versión y conserva el historial anterior. La acción de alta requiere permiso de gestión de personal.

**Comprobación:** después de guardar, debe verse la versión nueva y seguir disponible la anterior. Los archivos del legajo requieren almacenamiento persistente configurado en el backend.

## 3. Asistencia y ausencias

El backend permite marcar entrada y salida con ubicación, consultar asistencias, solicitar correcciones, pedir horas extra y someterlas a aprobación. También permite solicitar vacaciones u otras ausencias y consultar su estado. Las correcciones de asistencia y las horas extra tienen controles y aprobaciones antes de entrar en nómina.

**Web → Personal → Configuración de ausencias.** Consultá los tipos de ausencia y, si tenés el permiso correspondiente, administrá los saldos de vacaciones por gestión.

**Web → Personal → Bandeja de ausencias.** El jefe o responsable autorizado consulta solicitudes pendientes, abre cada una y decide **Aprobar** o **Rechazar**. En vacaciones se revisan los días hábiles; una licencia médica exige un comprobante del legajo del mismo empleado. Una solicitud pendiente puede impedir el cálculo de la nómina del periodo.

La web de este checkout no ofrece aún una pantalla para marcar entrada/salida, solicitar ausencias propias ni aprobar horas extra. Esas operaciones existen en la API. La visibilidad de la bandeja puede variar por permisos: la entrada del menú y la ruta usan códigos distintos; conviene comprobar el acceso con el rol real antes de la demostración.

## 4. Periodos, cálculo y boletas de nómina

**Web → `/nomina/periodos`.** Con una empresa seleccionada, la pantalla lista los periodos. Para un periodo existente, **Calcular** aplica las reglas y datos vigentes; cuando el estado es `CALCULADO`, **Aprobar** cierra el resultado. La pantalla actual lista, calcula y aprueba, pero no tiene un botón para abrir un periodo nuevo. El backend sí permite abrirlo mediante `POST /api/v1/nomina/periodos`.

**Web → Nómina → Boletas de pago.** El usuario autorizado consulta las boletas de la empresa y puede abrir su detalle. **Cuenta → Mis boletas** muestra únicamente las boletas propias aprobadas y permite imprimirlas.

**Antes de calcular:** verificá contratos, asistencias, ausencias, solicitudes de horas extra, estructura salarial, parámetros legales vigentes y datos tributarios. Si faltan datos o hay incidencias pendientes, el backend puede bloquear el cálculo. El RC-IVA usa datos F110 y saldos registrados; el sistema no obtiene ni presenta el F110 ante el SIN.

**Límite importante:** el motor de nómina existe, pero no se debe usar para pagos reales hasta que el responsable de nómina valide con planillas aprobadas el prorrateo, las tasas, los casos especiales y los resultados. Los casos de horas extra nocturnas, dominicales o de feriado requieren revisión particular. Ver [estado técnico del Sprint 3](sprint3_backend.md) y [ejemplo ficticio](nomina_ejemplo_ficticio.md).

## 5. Horario del respaldo automático según el plan

**Web → Administración → Respaldos por empresa.** El administrador de empresa puede ver el último respaldo, el historial y descargar las copias autorizadas. Si su plan incluye **Elegir hora del respaldo automático** y su rol tiene `backup:configurar`, aparece **Programación automática**: elegí la hora de Bolivia y pulsá **Guardar hora**. El horario predeterminado es **02:00, hora de Bolivia**. La función está prevista inicialmente para el plan Empresarial, pero el administrador global puede cambiar las casillas del catálogo de planes.

El administrador global selecciona una empresa y puede, además, activar o pausar su copia diaria. Un administrador de empresa **solo puede cambiar la hora de su propia empresa**; no puede activar o pausar las copias desde ese panel. El backend vuelve a usar las 02:00 si el plan deja de incluir la función. El servicio que programa las copias debe estar habilitado para que el horario tenga efecto.

Si el permiso se acaba de desplegar, cerrá sesión y volvé a entrar para actualizar los permisos del usuario.

## 6. Aplicación móvil: alcance comprobado en este código

La rama local móvil revisada contiene acceso a suscripciones, respaldos por empresa, reportes y chatbot. **No encontré en ella las pantallas de legajo, contratos, asistencia, ausencias, equipo o boletas del Sprint 3.** No deben presentarse como funciones comprobadas del APK hasta integrar y probar la rama móvil que las implemente. Que el backend tenga endpoints no significa que el APK ya muestre sus pantallas.

## 7. Referencia de la API

El contrato vigente se consulta en `/docs` o `/openapi.json` del backend. Las familias principales son `/api/v1/personal` (legajo, contratos, asistencia y ausencias), `/api/v1/nomina` (periodos y boletas) y `/api/v1/respaldos-empresa` (copias y configuración). Swagger muestra los métodos, campos y respuestas exactas de cada operación.

## 8. Recorrido breve para una demostración

1. Entrar como administrador de empresa y abrir la ficha de un empleado.
2. Consultar su contrato e historial; registrar una nueva versión en un entorno de prueba.
3. Mostrar tipos de ausencia y una solicitud pendiente en la bandeja; resolverla con un jefe autorizado.
4. Abrir un periodo de prueba previamente creado, calcularlo y revisar los mensajes de validación. Aprobarlo solo si los datos y reglas fueron verificados para esa demostración.
5. Consultar la boleta resultante y, con la cuenta del empleado, comprobar **Mis boletas**.
6. En una empresa cuyo plan incluya la función, cambiar la hora del respaldo y comprobar que el panel conserva el valor al recargar.

Usá datos ficticios para la demostración y evitá tratar una boleta de ejemplo como liquidación aprobada para pago.
