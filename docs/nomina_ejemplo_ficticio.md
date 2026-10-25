# Nomina ficticia de prueba: septiembre de 2025

Estos cinco trabajadores y sus importes son inventados. No corresponden a
Farmacorp ni constituyen una planilla presentada ante el Estado. Los importes
esperados se comprueban en `tests/unit/test_payroll_synthetic.py`.

## Criterios del ejemplo

- Mes de 30 dias. La sugerencia de prorrateo cuenta dias calendario cubiertos
  por el contrato y resta dias calendario de licencias sin goce aprobadas.
  Haber sugerido = salario mensual x dias pagables / dias calendario del mes,
  redondeado al centavo. **Es una convencion de simulacion, no una formula
  legal general ni una politica aprobada de una empresa.** En meses de 28, 29
  o 31 dias se usa la duracion real del mes. RRHH debe registrar y revisar el
  haber antes de calcular; la sugerencia no se incorpora automaticamente.
- Las tasas de prueba son AFP laboral 12,21%, solidario laboral 0,50%, CNS
  patronal 10%, vivienda patronal 2%, riesgo profesional 1,71% y solidario
  patronal 3,50%. AFP + solidario laboral suman 12,71%. Estas tasas estan
  **solo en la prueba** y no se cargan en `parametro_valor` ni en produccion.
- El Aporte Nacional Solidario se calcula con los tramos que implementa el
  backend para el periodo indicado. El RC-IVA de la quinta persona (Bs 500)
  es un dato ficticio externo; el sistema no lo determina. Los demas RC-IVA
  de prueba son cero. No son una declaracion tributaria.
- Las horas extra de la cuarta persona (Bs 200 por cuatro horas) son un
  importe ficticio autorizado: Bs 6000 / (30 dias x 8 horas) x 2 x 4 horas.
  El backend recibe ese monto luego de la autorizacion de RRHH; no impone
  esa formula para todas las jornadas.
- Cada concepto se redondea a centavos con `ROUND_HALF_UP` antes de sumar.

| Caso ficticio | Dias pagados | Haber basico | Horas extra | Total ganado | Descuentos | Liquido pagable | Aportes patronales |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Ana, mes completo | 30 | 6000,50 | 0,00 | 6000,50 | 762,66 | 5237,84 | 1032,69 |
| Bruno, ingreso el 16/09 | 15 | 3000,00 | 0,00 | 3000,00 | 381,30 | 2618,70 | 516,30 |
| Carla, licencia sin goce 10-11/09 | 28 | 5600,00 | 0,00 | 5600,00 | 711,76 | 4888,24 | 963,76 |
| Diego, cuatro horas extra autorizadas | 30 | 6000,00 | 200,00 | 6200,00 | 788,02 | 5411,98 | 1067,02 |
| Elena, ANS y RC-IVA externo ficticio | 30 | 27000,00 | 0,00 | 27000,00 | 4207,50 | 22792,50 | 4646,70 |

En la quinta boleta: AFP Bs 3296,70, solidario laboral Bs 135,00,
ANS Bs 275,80 y RC-IVA externo Bs 500,00. Suman Bs 4207,50.

## Referencias para contrastar, no para certificar esta simulacion

- Ministerio de Trabajo, instructivo OVT-T02: campos `Dias pagados`,
  `Haber basico`, `Horas extra` y `Monto horas extra`:
  https://ovt.mintrabajo.gob.bo/ws/manuales?nombre=OVTDJ-T02
- Gestora Publica, boletin a septiembre de 2025: tasas SIP y tramos ANS:
  https://www.gestora.bo/archivos/bajar?id=5731
- ASUSS, referencia del aporte patronal de salud del 10%:
  https://www.asuss.gob.bo/wp-content/uploads/2024/03/REGLAMENTO-DE-SEGUROS-DELEGADOS_CON-FIRMAS.pdf
- Gestora Publica, referencia del 2% patronal de vivienda:
  https://www.gestora.bo/pdf/folletos/1%20Tript%20Trab%20Dependientes.pdf
- SIN, planilla tributaria con F-110 y saldos anteriores:
  https://siatinfo.impuestos.gob.bo/index.php/planilla-tributaria

Antes de utilizar sueldos reales: revisar vigencia de tasas aplicables, politica
de prorrateo y jornadas, calcular RC-IVA en la planilla del SIN, y validar
resultados con el responsable de nomina. Esta prueba no reemplaza esas tareas.
