# SaaS y Stripe Sandbox

Esta integración funciona únicamente con Stripe Test Mode. El backend nunca recibe ni
almacena números de tarjeta, CVV o datos sensibles de pago.

## Variables del backend en Railway

```ini
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_CHECKOUT_SUCCESS_URL=https://TU-FRONTEND.up.railway.app/suscripcion/resultado?session_id={CHECKOUT_SESSION_ID}
STRIPE_CHECKOUT_CANCEL_URL=https://TU-FRONTEND.up.railway.app/suscripcion
STRIPE_PORTAL_RETURN_URL=https://TU-FRONTEND.up.railway.app/suscripcion
SUBSCRIPTION_GRACE_DAYS=3
```

No se necesita `VITE_STRIPE_PUBLISHABLE_KEY`: el navegador se redirige al Checkout
alojado por Stripe. Las claves `sk_test_...` y `whsec_...` pertenecen solamente al backend.

## Configuración en Stripe

1. Activar **Test mode**.
2. Crear un producto y un precio mensual por cada plan cobrable.
3. Copiar cada `price_...` en **Planes y suscripciones** dentro de SSAS.
4. Crear un webhook con URL
   `https://TU-BACKEND.up.railway.app/api/v1/webhooks/stripe`.
5. Suscribirlo a `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid` e
   `invoice.payment_failed`.
6. Copiar su signing secret `whsec_...` a `STRIPE_WEBHOOK_SECRET`.
7. Configurar Customer Portal en Test mode.

## Migración y despliegue

El backend debe conservar como Pre-deploy Command:

```text
alembic upgrade head
```

La migración `20260915_0005` amplía planes y suscripciones, crea `plan_modulo` y
`stripe_evento`, y asigna un plan inicial a las empresas existentes. Si detecta dos
suscripciones para una misma empresa se detiene sin borrar información.

## Reconciliación periódica

Crear un servicio Cron de Railway, usando el mismo repositorio y variables del backend,
con este comando diario:

```text
python -m ssas.suscripciones.infrastructure.cli.reconcile
```

El comando vence periodos de prueba, respeta cancelaciones al final del periodo y
suspende pagos fallidos al terminar la gracia. Es idempotente y registra cada cambio en
la bitácora.

## Demostración

Usar tarjetas de prueba oficiales de Stripe para demostrar pago aprobado, rechazado y
pago fallido. Verificar después de cada prueba:

- El webhook aparece procesado una sola vez en `stripe_evento`.
- Solo cambia la suscripción del tenant correspondiente.
- Los módulos y límites se actualizan sin borrar datos.
- El evento aparece en la bitácora.
- Una firma inválida responde HTTP 400.

No activar Live Mode ni utilizar tarjetas reales para la demostración académica.
