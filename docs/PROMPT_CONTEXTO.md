Retomamos Claimline, nuestro proyecto para el hackathon AWS CDS Agentic AI. Responde siempre en español. Este es el estado a 23 de octubre de 2026.

## Qué es
Claimline es un agente de IA que tramita partes de accidente de coche por WhatsApp. La entrega es el martes 27 de octubre de 2026 y la demo se graba el domingo 25.

- **BothSides (demo principal):** tras un choque, los dos conductores escriben al mismo número de WhatsApp, cada uno en su idioma. El agente:
  1. pregunta primero por heridos;
  2. da al conductor A un enlace `JOIN <código>` para el conductor B;
  3. recoge la versión de cada uno;
  4. compara las versiones;
  5. pregunta solo por los conflictos, sin culpar a nadie;
  6. al final, envía un informe por email a las dos aseguradoras.
- **First Call (segunda demo, opcional):** el asegurado avisa a su aseguradora por WhatsApp.
- WhatsApp va por AWS End User Messaging Social porque el premio de Meta lo exige. Nada de WhatsApp Web, Baileys ni Twilio.
- La spec está en https://claude.ai/artifact/WFr85iB6Fy4Pp2m7ThAQte (copia en `docs/spec.html`). Todavía dice us-east-1, pero la región real es eu-west-1.
- El documento de progreso está en https://claude.ai/artifact/1DG1XZwqSG9u4JArTMxTkD.

## Dónde está
- Repo local en `D:\proyectos\claimline`. GitHub privado: https://github.com/jorgeantonio-gif/claimline, rama `main`, último commit `c54200e`.
- Cuenta AWS compartida 888564397690, perfil de CLI `test`, región **eu-west-1**.
- Número de WhatsApp: +51 992 861 202, con `phone-number-id-8cf9d74a3a8a484582764cb617547642` y `waba-5172958319fc498bb36706462f967d41`.

## Reglas de la cuenta (obligatorias)
- Todo recurso se llama `test-claimline-…`. Los buckets se llaman `test-eng-claimline-…`. En AgentCore no se admiten guiones, así que allí se usa `test_claimline_…`. Los nombres están centralizados en `infra/naming.py`.
- Todo lleva la etiqueta `Owner = test`; `app.py` la añade sola.
- No tocar las instancias `test` y `test-2`, su disco, su IP elástica ni el bucket `test-eu-9b82d5`: son producción de otra persona.
- Las claves solo están en `~/.aws/credentials`. Nunca van en código, git ni chat, y no hay que leer ese archivo.
- El usuario `test` NO puede leer IAM, DynamoDB, la Memory de AgentCore ni la configuración de las Lambdas, y tampoco puede invocar el Runtime. Sí puede leer CloudFormation y CloudWatch Logs y llamar a Claude en Bedrock. Para diagnosticar se usan los eventos de CloudFormation y los logs.

## Arquitectura desplegada (pila `test-claimline-core`)
Recorrido de un mensaje: WhatsApp → EUM Social → tema SNS `test-claimline-inbound` → Lambda `test-claimline-router` (descarta duplicados en la tabla messages y copia los medios al bucket `test-eng-claimline-media-888564397690`) → AgentCore Runtime `test_claimline_agent-CNkM2nAZ5A` → respuesta por la Lambda `test-claimline-send`.

- **Agente:** Strands 1.62 sobre bedrock-agentcore 1.24, modelo `eu.anthropic.claude-opus-5-5`. Sonnet y Haiku 5.5 piden suscripción de Marketplace, por eso no se usan.
- **Historial:** en AgentCore Memory `test_claimline_memory-DD9Ux47AWU`, con una sesión `<caso>-<rol>` por conductor y caso.
- **Tablas DynamoDB** `test-claimline-`: cases, parties, facts, policies, events, outreach, messages. En parties, cada teléfono tiene un puntero `PHONE#<hash>/ACTIVE` a su caso activo, y cada conductor una fila `NOTES#<rol>` con los mensajes que le envió la conversación del otro.
- **Sesión del router:** `wa-v<versión del runtime>-<hash del teléfono>`. Así, cada despliegue se aplica al momento.
- **Logs:** cada mensaje deja una línea JSON `{caseId, role, event, otherJoined, msgId}` en `/aws/bedrock-agentcore/runtimes/test_claimline_agent-CNkM2nAZ5A-DEFAULT`.

## Código
| Ruta | Qué hace |
|---|---|
| `agent/main.py` | Punto de entrada; `build_agent()` monta el agente de un turno; respuestas fijas bilingües para RESET y JOIN fallido; `drop_reasoning()` quita del historial los bloques de razonamiento |
| `agent/prompts.py` | Reglas y prompt según la situación: rol, caso, evento, contexto para B, notas del otro conductor |
| `agent/cases.py` | Casos y conductores sin LLM: códigos JOIN, RESET, hechos, notas, `both_versions_given()` |
| `agent/tools.py` | Herramientas `record_fact`, `set_language`, `reconcile_case`, `message_other_driver` y `handoff_human` |
| `agent/reconcile.py` | Clasifica cada hecho en AGREED, ONLY_A, ONLY_B o CONFLICT. Tolera 10 km/h y 10 minutos. Marca CONFLICT `signal_state@crossing` si los dos dicen tener su semáforo en verde |
| `agent/judge.py` | Claude decide si dos textos libres dicen lo mismo; nunca juzga números ni horas |
| `lambdas/router`, `lambdas/send` | Entrada de mensajes y único punto de envío |
| `infra/core_stack.py`, `infra/agent_stack.py` | La pila de CDK, con el agente como construct dentro de core |
| `scripts/simulate.py` | Simula al conductor A (español) y al B (inglés) con Claude real y DynamoDB y WhatsApp en memoria; no toca AWS |
| `tests/test_reconcile.py` | 8 tests |

## Estado
- BothSides funciona de punta a punta con dos móviles reales (caso ZM4X65, 23 de octubre). El orden fue: RESET, JOIN, la versión de cada uno, comparación automática, y la pregunta del semáforo enviada una sola vez a cada conductor, sin culpar a nadie. Una captura del chat de A lo confirma.
- Desde cualquier teléfono, `RESET` (la palabra exacta) lo desvincula de su caso. El siguiente mensaje abre un caso nuevo, así que se puede ensayar con los mismos móviles.
- Un `JOIN` con un código que no existe, desde un teléfono sin caso, responde con un texto fijo y no abre ningún caso.

## Problemas ya resueltos (no repetirlos)
- Bedrock rechaza los bloques de razonamiento restaurados de Memory, porque el system prompt cambia entre turnos. Por eso existe `drop_reasoning()`.
- Las sesiones de AgentCore siguen ejecutando el código viejo hasta 15 minutos de inactividad. Por eso la sesión lleva la versión del Runtime.
- El juez necesita `maxTokens` alto (1024), porque Opus razona antes de contestar.
- Con "usted", "su vehículo" es ambiguo. El prompt obliga a decir "su propio vehículo" o "el vehículo del otro conductor".

## Cómo trabajar
1. Cambiar el código y ejecutar `.venv\Scripts\python -m unittest discover -s tests -t .`.
2. Probar con `.venv\Scripts\python scripts\simulate.py`.
3. Ejecutar `cdk diff -c wabaPhoneNumberId=phone-number-id-8cf9d74a3a8a484582764cb617547642` y revisar qué cambia antes de desplegar.
4. Ejecutar `cdk deploy --require-approval never -c wabaPhoneNumberId=phone-number-id-8cf9d74a3a8a484582764cb617547642`.
5. Hacer commit y push.

Desde Git Bash, usar `MSYS_NO_PATHCONV=1` en los comandos de `aws logs`. El bucket de medios es RETAIN: si falla un primer despliegue, queda huérfano y hay que borrarlo.

## Pendiente
1. Notas de voz: transcribirlas con Transcribe (probar OGG/Opus directo) para que el conductor cuente su versión hablando.
2. Informe en PDF y envío por SES a las dos aseguradoras. Falta que el compañero verifique en SES un dominio o los correos de prueba.
3. WhatsApp Flow de aprobación (primero estático).
4. Guardrails y traspaso a humano completo.
5. Actualizar la spec (eu-west-1, perfil `test`, "ALTA" en First Call), el README final, JUDGE_TEST.md, ORIGINAL_WORK.md y el diagrama de arquitectura.
6. Tareas del compañero: correos de SES, alerta de presupuesto de unos $50, rotar la access key que se compartió en el PDF y activar MFA en el usuario `test`.

Empieza leyendo el documento de progreso y `git log`. Comprueba `aws sts get-caller-identity --profile test` y dime el siguiente paso.
