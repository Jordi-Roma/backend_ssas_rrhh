# Sprint 4: contratos de backend

La especificación ejecutable se genera desde FastAPI en `/openapi.json` y se consulta en `/docs`.
La colección de solicitudes está en `docs/postman/sprint4_backend.postman_collection.json`.

## Capacitación

Todas las rutas usan el prefijo `/api/v1/capacitacion`. Un token de empresa opera únicamente
sobre su `empresa_id`; la cuenta global debe indicar `empresa_id` en la consulta.

| Operación | Ruta | Permiso |
| --- | --- | --- |
| Catálogo/curso | `GET /cursos`, `GET /cursos/{id}` | `capacitacion:ver` o `capacitacion:aprender` |
| Crear/editar/eliminar | `POST /cursos`, `PATCH/DELETE /cursos/{id}` | `capacitacion:gestionar` |
| Publicar | `POST /cursos/{id}/publicar` | `capacitacion:gestionar` |
| Lecciones | `GET/POST /cursos/{id}/lecciones`, `PATCH/DELETE /lecciones/{id}` | lectura o gestión |
| Material | `POST /materiales` (multipart `archivo`), `GET /materiales/{nombre}` | gestión o lectura |
| Asignar | `POST /inscripciones` | `capacitacion:gestionar` |
| Avance | `GET /inscripciones`, `GET /mis-cursos`, `POST /inscripciones/{id}/lecciones/{id}/completar` | gestión o aprendizaje |
| Calificar | `POST /inscripciones/{id}/calificar` | `capacitacion:gestionar` |
| Certificado | `GET /inscripciones/{id}/certificado` | titular o gestor |
| Habilidad | `POST /empleado-habilidades` | `capacitacion:gestionar` |

La asignación acepta **uno** de `empleado_id` y `departamento_id`. En el segundo caso usa
contratos vigentes y evita inscripciones duplicadas. El progreso se calcula con las lecciones
terminadas. Un curso completado aprueba según `nota_minima`; los quiz se califican en el servidor
con las respuestas recibidas. El certificado PDF se genera al descargarlo, sin URL pública.

Para una lección `QUIZ`, `contenido_texto` es un JSON con
`{"preguntas":[{"enunciado":"...","opciones":["A","B"],"correcta":0}]}`.
Las respuestas correctas se omiten de la lectura del alumno; el gestor puede verlas para editar el cuestionario. El alumno envía
`{"respuestas":[0]}` al completar. Los materiales aceptan PDF, MP4, PNG y JPG hasta 20 MB.
En producción, `CAPACITACION_FILES_DIRECTORY` debe apuntar a un volumen persistente.

## Indicadores y exportación

`GET /api/v1/indicadores?desde=YYYY-MM-DD&hasta=YYYY-MM-DD` devuelve rotación,
ausentismo, días promedio de contratación, dotación por departamento y embudo de postulaciones.
El rango máximo es 367 días. Rotación = salidas / promedio de dotación inicial y final.
Ausentismo = días laborables de solicitudes aprobadas / días laborables disponibles de esa
dotación promedio. La contratación se mide desde la postulación hasta el ingreso de empleados
vinculados a postulaciones `CONTRATADA`; si no hay casos, el promedio es `null`.

`POST /api/v1/reportes/exportar/csv` recibe el mismo `ReporteConfig` que las exportaciones
HTML/XLSX/PDF. Devuelve UTF-8 con BOM, encabezados y protección ante fórmulas de hojas de cálculo.
La consulta conserva el filtro por empresa y la lista permitida de columnas.

## Respaldo y restauración en limpio

El respaldo manual global de la API sigue en `/api/v1/respaldos`. Para el programado:

1. Configurar `DATABASE_URL` y `BACKUP_OUTPUT_DIRECTORY` en el **servicio de cron**, apuntando
   este último a un volumen persistente fuera del contenedor. No reutilizar el volumen de la BD.
2. Programar `PYTHONPATH=src python scripts/backup_global_programado.py` diariamente, por ejemplo
   a las 02:00 en la zona horaria del servicio. En Railway, configurar un cron service con
   expresión `0 6 * * *` si se desea 02:00 de Bolivia (UTC-4).
3. Verificar en cada ejecución que existan `ssas-global-<fecha>-<id>.dump` y `.json`, y que
   el SHA-256 del archivo coincida con el manifiesto. Cada ejecución genera una versión nueva.
4. Crear una base PostgreSQL **vacía y descartable** llamada `ssas_restore_<nombre>`.
5. Configurar `TEST_RESTORE_DATABASE_URL` hacia esa base y `BACKUP_DUMP_PATH` hacia el dump.
   Ejecutar `PYTHONPATH=src python scripts/verificar_restore_global.py`. El script rechaza
   destinos con tablas o con otro nombre, comprueba hash, restaura y compara conteos de
   empleados y contratos por empresa. También comprueba contratos sin cruce de empresa.
6. Registrar la salida del verificador, fecha, dos empresas y persona que ejecutó la prueba.
   El criterio de aceptación T4-26 exige que la ejecute alguien distinto del autor del script.

**El respaldo programado cubre la base PostgreSQL**, no archivos de materiales ni CV.
Estos archivos requieren copia aparte del volumen persistente. No restaurar sobre producción
para verificar T4-26.
