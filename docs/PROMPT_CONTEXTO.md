Retomamos Claimline, nuestro proyecto para el hackathon AWS CDS Agentic AI. Responde siempre en español. Este es el estado a primera hora del 25 de octubre de 2026.

## Qué es
Claimline es un agente de IA que tramita partes de accidente de coche por WhatsApp. La entrega es el martes 27 de octubre de 2026 y la demo se graba el domingo 25.

- **BothSides (demo principal):** tras un choque, los dos conductores escriben al mismo número de WhatsApp, cada uno en su idioma, por texto o con notas de voz. El agente:
  1. pregunta primero por heridos;
  2. da al conductor A un enlace `JOIN <código>` para el conductor B;
  3. recoge la versión de cada uno;
  4. compara las versiones en código;
  5. pregunta solo por los conflictos, sin culpar a nadie;
  6. manda a cada uno un formulario de WhatsApp (Flow) para aprobar el informe;
  7. al aprobar los dos, genera el informe en PDF (`agent/report.py`, sin modelo) y lo manda a los dos por WhatsApp; el envío a las aseguradoras por SES sigue pendiente.
- **First Call (segunda demo, opcional):** el asegurado avisa a su aseguradora por WhatsApp.
- WhatsApp va por AWS End User Messaging Social porque el premio de Meta lo exige. Nada de WhatsApp Web, Baileys ni Twilio.
- La spec está en https://claude.ai/artifact/WFr85iB6Fy4Pp2m7ThAQte (copia en `docs/spec.html`). Todavía dice us-east-1, pero la región real es eu-west-1.
- El documento de progreso está en https://claude.ai/artifact/1DG1XZwqSG9u4JArTMxTkD. El resumen visual del proyecto está en `docs/overview.html`.

## Dónde está
- Repo local en `D:\proyectos\claimline`. GitHub privado: https://github.com/jorgeantonio-gif/claimline, rama `main`.
- Cuenta AWS compartida 888564397690, perfil de CLI `test`, región **eu-west-1**.
- Número de WhatsApp: +51 992 861 202, con `phone-number-id-8cf9d74a3a8a484582764cb617547642` y `waba-5172958319fc498bb36706462f967d41`.
- El acceso a WhatsApp está limitado ahora mismo: se prueba con el **prototipo local** (ver abajo).

## Reglas de la cuenta (obligatorias)
- Todo recurso se llama `test-claimline-…`. Los buckets se llaman `test-eng-claimline-…`. En AgentCore no se admiten guiones, así que allí se usa `test_claimline_…`. Los nombres están centralizados en `infra/naming.py`.
- Todo lleva la etiqueta `Owner = test`; `app.py` la añade sola.
- No tocar las instancias `test` y `test-2`, su disco, su IP elástica ni el bucket `test-eu-9b82d5`: son producción de otra persona.
- Las claves solo están en `~/.aws/credentials`. Nunca van en código, git ni chat, y no hay que leer ese archivo. La clave de ElevenLabs está en `~/.claimline/env`, también fuera del repo.
- El usuario `test` NO puede leer IAM, DynamoDB, la Memory de AgentCore ni la configuración de las Lambdas, y tampoco puede invocar el Runtime ni usar Transcribe o Polly. Sí puede leer CloudFormation y CloudWatch Logs y llamar a Claude en Bedrock.

## Arquitectura desplegada (pila `test-claimline-core`)
Recorrido de un mensaje: WhatsApp → EUM Social → tema SNS `test-claimline-inbound` → Lambda `test-claimline-router` (descarta duplicados, copia los medios al bucket `test-eng-claimline-media-888564397690`, transcribe las notas de voz con Transcribe, lee las respuestas del formulario y registra los estados de entrega de Meta) → AgentCore Runtime `test_claimline_agent-CNkM2nAZ5A` → respuesta por la Lambda `test-claimline-send`.

- **Agente:** Strands 1.62 sobre bedrock-agentcore 1.24, modelo `eu.anthropic.claude-opus-5-5`. Sonnet y Haiku 5.5 piden suscripción de Marketplace, por eso no se usan.
- **Historial:** en AgentCore Memory `test_claimline_memory-DD9Ux47AWU`, con una sesión `<caso>-<rol>` por conductor y caso.
- **Tablas DynamoDB** `test-claimline-`: cases, parties, facts, policies, events, outreach, messages.
- **Formulario de aprobación:** WhatsApp Flow `test-claimline-approval`, id `29183837704562024`, en **borrador** (`APPROVAL_FLOW_MODE = "draft"` en `infra/agent_stack.py`). Se crea y publica con `scripts/flow.py`. Publicar es irreversible: solo con permiso del usuario.
- **Interruptor `WHATSAPP_ON`:** el runtime desplegado lleva `WHATSAPP_ON=1` (envía por la Lambda send). El prototipo local usa `0`.
- **Logs:** `/aws/lambda/test-claimline-router` y `/aws/bedrock-agentcore/runtimes/test_claimline_agent-CNkM2nAZ5A-DEFAULT` (una línea JSON por mensaje con caso, rol y evento).

## Prototipo local de WhatsApp
`.venv\Scripts\python -m pipeline.server` y abrir http://localhost:8765.

- Dos "móviles" (A en español, B en inglés) hacen de WhatsApp y Meta. Detrás corre el **código desplegado**: el router y el send Lambda reales y el agente con Claude real. Solo se cambian los clientes de AWS (`pipeline/fake_aws.py`), y ElevenLabs (`pipeline/voice.py`) reemplaza a Transcribe.
- Meta emulado (`pipeline/meta.py`) valida cada mensaje como Meta: ventana de 24 horas, límites de texto y el formulario contra `flows/approval.json`. La página abre el formulario a partir de ese mismo Flow.
- Permite notas de voz (grabadas o generadas con ElevenLabs), fotos, ver el JSON de cada mensaje y cambiar de escenario: "Los dos en verde" o "Frenazo por un peatón".
- Lo único que no puede comprobar es si el WhatsApp real abre un Flow en borrador.

## Código
| Ruta | Qué hace |
|---|---|
| `agent/main.py` | Punto de entrada; describe cada mensaje (texto, voz, formulario); guarda las respuestas del formulario y pasa el caso a una persona tras dos rechazos sin corrección |
| `agent/prompts.py` | Reglas del agente y la situación de cada turno |
| `agent/tools.py` | `record_fact`, `set_language`, `reconcile_case`, `message_other_driver`, `send_approval_form`, `handoff_human` |
| `agent/channel.py` | Por dónde salen los mensajes (`WHATSAPP_ON`) |
| `agent/cases.py` | Casos, códigos JOIN, RESET, hechos, aprobaciones y rechazos, sin LLM. Sujetos A, B, `scene` y `third_party` |
| `agent/reconcile.py`, `agent/judge.py` | Comparación de versiones: AGREED, ONLY_A, ONLY_B o CONFLICT; tolera 10 km/h y 10 minutos; conflicto si los dos dicen tener su semáforo en verde |
| `lambdas/router`, `lambdas/send` | Entrada y salida de mensajes |
| `flows/approval.json`, `scripts/flow.py` | El formulario de WhatsApp y el script que lo crea y publica |
| `pipeline/` | Prototipo local de WhatsApp |
| `scripts/simulate*.py` | Simulaciones con Claude real, sin tocar AWS: texto, voz, rechazo y peatón |
| `agent/report.py` | Informe PDF del parte conjunto: secciones de la conciliación, citas de cada conductor, aprobaciones; se guarda en `reports/` del bucket y se envía a los dos |
| `tests/` | 35 tests |

## Estado
- BothSides funciona de punta a punta con dos móviles reales (caso ZM4X65, 23 de octubre) y con notas de voz reales (24 de octubre).
- El formulario de aprobación funciona en simulación y en el prototipo, con los dos conductores aprobando y el caso en `APPROVED`. **Falta probarlo en un móvil real**, porque sigue en borrador.
- Rechazos: aprobar significa "recoge lo que dijo cada uno", no aceptar la versión del otro. Al segundo "Algo está mal" sin corrección, el caso pasa a `HANDOFF` y se avisa a los dos.
- Escenario del peatón: lo que hizo un tercero (`third_party_action`) y el motivo de la maniobra (`cause`) se guardan y se comparan como cualquier dato, sin culpar a nadie.
- Informe PDF: al aprobar los dos, `agent/report.py` lo genera en código, se guarda en `reports/` del bucket y llega a los dos conductores como documento de WhatsApp. El agente no dice que se envió a una aseguradora, porque eso (SES) aún no existe. Probado en simulación y en el prototipo; en AWS real no se ha podido probar sin WhatsApp.
- Documentos para los jueces hechos (en inglés): `README.md` (con la sección "How we use WhatsApp" para el premio de Meta y la nota de costes), `JUDGE_TEST.md`, `ORIGINAL_WORK.md` y `docs/architecture.png` (fuente en `docs/architecture/`).
- Despliegue portable: `CLAIMLINE_ACCOUNT`/`CLAIMLINE_REGION` y `-c permissionsBoundary=` para otra cuenta; nuestro despliegue no cambia. El prototipo funciona con credenciales de cualquiera y sin clave de ElevenLabs (solo texto).
- Coste medido de un caso completo (`simulate_voice.py`): unos 247.000 tokens de entrada y 10.000 de salida en Claude, 135 s.

## Problemas ya resueltos (no repetirlos)
- Bedrock rechaza los bloques de razonamiento restaurados de Memory, porque el system prompt cambia entre turnos. Por eso existe `drop_reasoning()`.
- Las sesiones de AgentCore siguen ejecutando el código viejo hasta 15 minutos de inactividad. Por eso la sesión lleva la versión del Runtime.
- El juez necesita `maxTokens` alto (1024), porque Opus razona antes de contestar.
- `GetWhatsAppMessageMedia` usa la key como prefijo y añade `<mediaId>.<ext>`; el router busca el objeto real con `list_objects_v2`.
- `damage_part` guarda un valor por vehículo: el agente junta todas las piezas dañadas en uno.
- Con "usted", "su vehículo" es ambiguo: el prompt obliga a decir "su propio vehículo" o "el vehículo del otro conductor".
- El modelo a veces olvidaba un conflicto en el formulario: `send_approval_form` no lo envía si no lista exactamente los CONFLICT.
- Con mensajes largos el modelo decía "anotado" sin guardar los datos: el prompt exige una llamada a `record_fact` por dato antes de responder.
- El `__pycache__` del prototipo local se colaba en los paquetes de las Lambdas: `from_asset` lo excluye.

## Cómo trabajar
1. Cambiar el código y ejecutar `.venv\Scripts\python -m unittest discover -s tests -t .`.
2. Probar con `scripts\simulate_voice.py`, `simulate_refusal.py` o `simulate_pedestrian.py`, o en el prototipo local.
3. Ejecutar `cdk diff -c wabaPhoneNumberId=phone-number-id-8cf9d74a3a8a484582764cb617547642` y revisar qué cambia antes de desplegar.
4. Ejecutar `cdk deploy --all --require-approval never -c wabaPhoneNumberId=phone-number-id-8cf9d74a3a8a484582764cb617547642`.
5. Hacer commit y push.

Desde Git Bash, usar `MSYS_NO_PATHCONV=1` en los comandos de `aws logs`. El bucket de medios es RETAIN: si falla un primer despliegue, queda huérfano y hay que borrarlo.

## Pendiente
1. Envío del informe PDF a las aseguradoras por SES, cuando el compañero verifique los correos. El PDF ya se genera y llega a los dos conductores por WhatsApp.
2. Guion del vídeo (3 minutos máximo), ensayar y grabar con el prototipo (domingo 25).
3. Texto de Devpost con los títulos del baremo y la sección de WhatsApp (lunes 26); entrega el martes 27.
4. Decidir el acceso al repo: público con `LICENSE` MIT, o privado compartido con `testing@devpost.com` y `aws-cds-partner@amazon.com`. Revisar si las bases piden declarar la ayuda de IA (`ORIGINAL_WORK.md` la menciona). Oportunidad ACE.
5. Probar el formulario en un móvil real y decidir si se publica. Actualizar la spec (dice us-east-1).
6. Tareas del compañero: correos de SES, rotar la access key compartida, activar MFA y alerta de presupuesto de unos $50. Rotar la clave de ElevenLabs después de la demo.
7. Siguientes pasos (fuera de la demo): avisar a una persona real en `HANDOFF`, plazo para quien no responde, atropello con un solo conductor, guardrails de Bedrock y First Call.

Empieza leyendo el documento de progreso y `git log`. Comprueba `aws sts get-caller-identity --profile test` y dime el siguiente paso.
