# Correo con Resend

El backend utiliza SMTP para verificación de cuentas, recuperación de contraseñas,
envío de reportes y avisos de ausencias. Resend funciona con este transporte sin
instalar otra biblioteca.

Configurar **solo en las variables privadas del backend de Railway**:

```text
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USERNAME=resend
SMTP_PASSWORD=<clave de API de Resend, con permiso de envío>
SMTP_FROM_EMAIL=onboarding@resend.dev
SMTP_FROM_NAME=SSAS RRHH
SMTP_USE_TLS=true
SMTP_ONLY_EMAIL=jordirodriguez0806@gmail.com
```

No registrar la clave en Git, frontend ni móvil. `onboarding@resend.dev` solo
permite enviar al correo propietario de la cuenta Resend. El puerto 587 usa STARTTLS, compatible con
la implementación SMTP existente. No hace falta una variable `RESEND_API_KEY`:
la clave se usa como `SMTP_PASSWORD`.

Al crear, aprobar o rechazar una solicitud de ausencia el aviso se dirige
exclusivamente a `SMTP_ONLY_EMAIL`. Los mensajes no incluyen detalles médicos
ni el motivo de la ausencia; llevan a la pantalla autenticada correspondiente.
La ausencia se guarda antes de enviar. Si Resend falla, se registra el error en
el backend y la operación de RRHH permanece confirmada.

## Comprobantes de suscripción

Cuando Stripe confirma `invoice.paid`, el backend envía con la API de Resend
un correo a `SMTP_ONLY_EMAIL`. Adjunta un comprobante PDF propio con el diseño de SSAS RRHH, importe,
fecha, referencia y concepto. Si Stripe proporciona un enlace oficial, también
lo incluye en el mensaje. Esto cubre la compra inicial, cambios de plan con cobro
y renovaciones. Un cambio sin factura pagada no genera comprobante.
El PDF es un comprobante informativo y no sustituye una factura fiscal.

Todos los mensajes (cuentas, reportes, ausencias y comprobantes) salen del mismo
remitente `SMTP_FROM_EMAIL` y se entregan exclusivamente a `SMTP_ONLY_EMAIL`.
La variable anterior `SMTP_COPY_EMAIL` no se usa y puede eliminarse. Esta
dirección recibirá información de todas las empresas, incluidos reportes y
comprobantes. Los usuarios no recibirán verificaciones ni enlaces de
recuperación de contraseña en sus propias cuentas. Los mensajes emitidos
directamente por Stripe o servicios ajenos al backend se configuran aparte.

Se reutiliza la misma clave privada `SMTP_PASSWORD` como clave API de Resend;
no hace falta una segunda clave. El webhook conserva el pago confirmado aunque
el envío falle: responde con error para que Stripe reintente el aviso. La API
de Resend recibe como clave de idempotencia el ID de la factura, para reducir
duplicados en esos reintentos. Si Stripe ya tiene activado el envío automático
de facturas pagadas, desactivarlo para evitar que el cliente reciba dos correos.
