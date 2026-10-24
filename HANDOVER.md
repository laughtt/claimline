# Claimline · Handover

Estado a 24 de octubre de 2026. Grabación de la demo: **domingo 25**. Entrega del hackathon: **martes 27 de octubre de 2026**.

**Lo más urgente para ti:** que SES pueda enviar el informe a las aseguradoras. Basta con verificar dos o tres direcciones de prueba (3.1). Si no llega a tiempo, el informe PDF se mandará por WhatsApp como documento.

---

## 1. Qué es Claimline

Es nuestra entrada al hackathon **AWS CDS Agentic AI**: un agente de IA que tramita partes de accidente de coche por WhatsApp. La spec está en [Claimline Build Spec](https://claude.ai/artifact/WFr85iB6Fy4Pp2m7ThAQte) y en `docs/spec.html` (todavía dice us-east-1; la región real es **eu-west-1**). El progreso día a día está en [Claimline · Progreso y pendientes](https://claude.ai/artifact/1DG1XZwqSG9u4JArTMxTkD).

- **BothSides (demo principal).** Tras un choque, los dos conductores escriben al mismo número de WhatsApp, cada uno en su idioma, por texto o con notas de voz. El agente:
  1. pregunta primero si hay heridos;
  2. da al conductor A un enlace `JOIN <código>` para el conductor B;
  3. recoge la versión de cada uno;
  4. compara las versiones (`agent/reconcile.py`): de acuerdo, solo A, solo B o en conflicto;
  5. pregunta a los dos solo por los conflictos, sin culpar a nadie;
  6. los dos aprueban el parte (WhatsApp Flow, pendiente);
  7. envía el informe a las dos aseguradoras (PDF + SES, pendiente).
- **First Call (segunda demo, opcional).** El asegurado avisa a su aseguradora por WhatsApp. Antes manda "ALTA", que abre la ventana de 24 horas y permite botones sin plantillas aprobadas.

**Por qué WhatsApp va por AWS:** el premio de Meta exige **AWS End User Messaging Social**. No valen WhatsApp Web, librerías no oficiales (whatsapp-web.js, Baileys) ni intermediarios como Twilio.

## 2. Estado actual

| Parte | Estado |
|---|---|
| Número de WhatsApp +51 992 861 202 | Vinculado en eu-west-1 (`phone-number-id-8cf9d74a3a8a484582764cb617547642`) |
| Pila `test-claimline-core` | Desplegada (S3, DynamoDB, SNS, Lambdas, agente) |
| Agente en Bedrock AgentCore | Desplegado: Runtime `test_claimline_agent-CNkM2nAZ5A` + Memory, modelo Claude Opus 5.5 |
| BothSides de punta a punta | **Funciona** con dos móviles reales (caso ZM4X65, 23 de octubre) |
| Notas de voz | **Funcionan** con móvil real desde el 24 de octubre: Transcribe las pasa a texto en unos 12 s |
| Reinicio entre ensayos | Enviar `RESET` desde cada teléfono abre un caso nuevo |
| Informe PDF y envío por SES | Pendiente; falta SES (3.1) |
| WhatsApp Flow de aprobación | Pendiente |
| Código | Repo privado [jorgeantonio-gif/claimline](https://github.com/jorgeantonio-gif/claimline), rama `main` |

## 3. Lo que tienes que hacer tú (con tu usuario administrador)

### 3.1 SES para el informe (urgente)

El agente enviará el informe en PDF por email a las dos aseguradoras. SES está en sandbox, así que solo puede enviar a direcciones verificadas.

**Opción rápida (suficiente para la demo):**

1. En la consola de AWS, región **eu-west-1**, abrir **Amazon SES → Identities → Create identity**.
2. Elegir **Email address** y crear una identidad para cada dirección:
   - el remitente (por ejemplo, un Gmail del equipo);
   - las dos "aseguradoras" de la demo (pueden ser correos nuestros).
3. Abrir el correo de verificación que llega a cada dirección y pulsar el enlace.
4. Añadir la etiqueta **`Owner = test`** a cada identidad.
5. Pasarnos las tres direcciones.

**Opción completa (si hay tiempo):** verificar un dominio, crear el registro MX de `in.<dominio>` para recibir la respuesta del ajustador y pedir salir del sandbox.

### 3.2 Resto de tareas, por prioridad

- [ ] SES: verificar las direcciones de prueba y pasárnoslas (3.1)
- [ ] Rotar la access key del usuario `test` (se compartió en el PDF de la guía) y activar MFA en ese usuario
- [ ] Crear una alerta de presupuesto de unos $50
- [ ] Opcional: dar al usuario `test` la política de pruebas de voz (3.3), para probar audios sin móviles
- [ ] Opcional: activar Claude Sonnet 5.5 en Bedrock eu-west-1 (suscripción de Marketplace, abriéndolo una vez en el playground). Hoy usamos Opus 5.5, que funciona pero es más caro
- [ ] Opcional: decidir sobre RCS (agente de pruebas en EUM SMS, según tarifas y país de los móviles)

**Lo que necesitamos de vuelta:** las direcciones verificadas en SES y, si falla algún permiso, el texto exacto del error.

### 3.3 Política opcional para probar notas de voz sin móviles

Con esto podemos generar audios con Polly y pasarlos por Transcribe igual que hace el router. Solo admite trabajos llamados `test-claimline-*`. Añadirla al usuario `test` como política en línea `test-claimline-voice-test`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TranscribeTestJobs",
      "Effect": "Allow",
      "Action": ["transcribe:StartTranscriptionJob", "transcribe:GetTranscriptionJob", "transcribe:TagResource"],
      "Resource": "arn:aws:transcribe:eu-west-1:888564397690:transcription-job/test-claimline-*"
    },
    {
      "Sid": "TranscribeList",
      "Effect": "Allow",
      "Action": "transcribe:ListTranscriptionJobs",
      "Resource": "*"
    },
    {
      "Sid": "PollyVoices",
      "Effect": "Allow",
      "Action": ["polly:SynthesizeSpeech", "polly:DescribeVoices"],
      "Resource": "*"
    }
  ]
}
```

## 4. Cómo probar con los móviles

1. Cada móvil de prueba envía `RESET` al +51 992 861 202.
2. El conductor A escribe o manda una nota de voz contando que ha tenido un choque.
3. El agente pregunta por heridos y da a A un enlace o el código `JOIN XXXXXX`.
4. El conductor B envía `JOIN XXXXXX` **por texto** (por voz no funciona).
5. Cada uno cuenta su versión, en español o en inglés, por texto o por voz. Si los dos dicen que su semáforo estaba en verde, el agente pregunta a ambos por el semáforo.

Con notas de voz, las respuestas tardan unos 15–30 s más que con texto. El agente pide escribir las placas, porque la voz puede entenderlas mal.

## 5. Reglas de la cuenta

Todo va en la cuenta **888564397690**, usuario `test`, región **eu-west-1**.

- Todos los recursos se llaman `test-claimline-…`; los buckets, `test-eng-claimline-…-888564397690`. En AgentCore no se admiten guiones, así que allí es `test_claimline_…`. Los nombres están centralizados en `infra/naming.py`.
- Todo lleva la etiqueta `Owner = test`. `app.py` la pone a todo lo de CDK, y el router a los trabajos de Transcribe.
- No se tocan las instancias `test` y `test-2`, su disco, su IP elástica ni el bucket `test-eu-9b82d5` (producción).
- Las claves solo están en `~/.aws/credentials`, nunca en código, git ni chat.
- Las demás regiones están bloqueadas por la política `test-eu-west-1-only`.
- Los roles de la pila llevan como límite de permisos la política `test-claimline-deploy`.
- El usuario `test` no puede leer IAM, DynamoDB, la Memory de AgentCore ni la configuración de las Lambdas, ni invocar el Runtime. Se diagnostica con los eventos de CloudFormation y los logs de CloudWatch.

## 6. Arquitectura

**Recorrido de un mensaje:**

1. Un conductor escribe o manda una nota de voz al número de la aseguradora.
2. End User Messaging Social publica el evento en el tema SNS `test-claimline-inbound`.
3. La Lambda **router** descarta duplicados (tabla `messages`) y copia fotos y audios al bucket de medios.
4. Si es una nota de voz, el router la pasa a texto con **Amazon Transcribe** (OGG/Opus directo, detecta español o inglés). La transcripción queda en `transcripts/` del bucket.
5. El router llama al agente en **Bedrock AgentCore Runtime** (Strands + Claude Opus 5.5). El historial de cada conductor está en **AgentCore Memory**.
6. El agente guarda los hechos en DynamoDB, compara las dos versiones y, si hace falta, escribe al otro conductor.
7. La Lambda **send** envía las respuestas por WhatsApp. Es el único código que envía mensajes.

**Recursos de la pila `test-claimline-core`:**

| Recurso | Nombre |
|---|---|
| Bucket de medios (RETAIN) | `test-eng-claimline-media-888564397690` |
| 7 tablas DynamoDB | `test-claimline-` + cases, parties, facts, policies, events, outreach, messages |
| Tema SNS de entrada | `test-claimline-inbound` |
| Cola de errores | `test-claimline-dlq` (14 días) |
| Lambdas | `test-claimline-router` y `test-claimline-send` |
| Agente | Runtime `test_claimline_agent-CNkM2nAZ5A`, Memory `test_claimline_memory-DD9Ux47AWU`, roles `test-claimline-agent-role` y `test-claimline-memory-role` |

**Logs útiles:** `/aws/lambda/test-claimline-router` (transcripciones y errores) y `/aws/bedrock-agentcore/runtimes/test_claimline_agent-CNkM2nAZ5A-DEFAULT` (una línea por mensaje con caso, rol y evento).

## 7. Código

| Ruta | Qué hace |
|---|---|
| `infra/naming.py` | Todos los nombres: cuenta, región, prefijo, buckets |
| `infra/core_stack.py` | Pila core: S3, DynamoDB, SNS, DLQ, Lambdas router y send |
| `infra/agent_stack.py` | Agente en AgentCore (Runtime + Memory) y sus roles |
| `app.py` | Crea la pila, aplica `Owner = test` y el límite de permisos |
| `lambdas/router/handler.py` | Entrada: deduplica, guarda medios, transcribe notas de voz y llama al agente |
| `lambdas/send/handler.py` | Envío por WhatsApp (texto o interactivo) |
| `agent/main.py`, `agent/prompts.py` | Punto de entrada del agente y sus reglas |
| `agent/cases.py`, `agent/tools.py` | Casos, códigos JOIN, RESET, hechos y herramientas del agente |
| `agent/reconcile.py`, `agent/judge.py` | Comparación de versiones; Claude decide si dos textos libres dicen lo mismo |
| `scripts/simulate.py`, `scripts/simulate_voice.py` | Simulan a los dos conductores (por texto y por voz) con Claude real, sin tocar AWS |
| `tests/` | 12 tests (reconciliación y transcripción) |
| `docs/PROMPT_CONTEXTO.md` | Contexto para retomar el proyecto en una sesión nueva de Claude |

**Comandos:**

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m unittest discover -s tests -t .
.venv\Scripts\python scripts\simulate_voice.py
cdk diff -c wabaPhoneNumberId=phone-number-id-8cf9d74a3a8a484582764cb617547642
cdk deploy --all --require-approval never -c wabaPhoneNumberId=phone-number-id-8cf9d74a3a8a484582764cb617547642
aws sts get-caller-identity --profile test
```

## 8. Fechas clave

| Fecha | Qué |
|---|---|
| Sáb 24 oct | Notas de voz terminadas; siguiente, WhatsApp Flow e informe PDF |
| Dom 25 oct | Grabación de la demo |
| Mar 27 oct | Entrega |

## 9. Riesgos

| Riesgo | Qué hacemos |
|---|---|
| SES no se verifica a tiempo | El informe PDF se envía por WhatsApp como documento |
| Retraso de las respuestas con notas de voz (15–30 s) | En la grabación, mezclar texto y voz, o recortar las esperas en el montaje |
| Las claves del PDF quedaron expuestas | Rotar la access key y activar MFA |
| Coste de Opus 5.5 | Alerta de presupuesto; activar Sonnet 5.5 si da tiempo |

## 10. Dudas abiertas

- ¿Qué direcciones de correo usamos para el remitente y las dos aseguradoras de la demo?
- ¿Quién graba la demo el domingo y con qué móviles?
