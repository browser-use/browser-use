# Enterprise controls

The agent runs on the application machine.
Bash and JavaScript have that machine's permissions.
A remote browser separates browser execution from application execution.
It does not isolate the agent host.

## Supported control boundaries

| Control          | SDK responsibility                                    | External responsibility                                                   |
| ---------------- | ----------------------------------------------------- | ------------------------------------------------------------------------- |
| Domains          | Normalized navigation rules, denials, frames, popups  | Browser provider enforces broader browser network policy                  |
| CDP restrictions | Pass authenticated connection configuration           | Browser or trusted gateway restricts CDP methods                          |
| Approvals        | Bounded before-tool callbacks and clear denial        | Application supplies approval UI and durable approval records             |
| Secrets          | Domain-scoped insertion and configured text redaction | Application resolves vault values and controls storage                    |
| Host execution   | Explicit tools, deadlines, cancellation               | Deployment controls filesystem, process, and outbound network permissions |
| Logs             | Events, local journal, history, classified errors     | Application controls storage access and retention                         |
| Recordings       | Optional frames, manifest, export, failure status     | Storage owner controls raw captures and retention                         |
| Setup            | Trusted application setup and document initialization | Application verifies scripts and their side effects                       |

The library does not implement a client-side CDP method blocklist.
Generated host code can create another connection.
A browser or trusted gateway must enforce a real method restriction.
That boundary must reject alternate access paths.

The default domain guard intercepts document navigation.
It does not restrict every browser subresource or generated Node request.
The library must report its enforcement scope accurately.
Browser-level enforcement requires a provider capability acknowledgment.

## Approvals and callbacks

Before-tool callbacks can reject a tool call.
A callback sees one JavaScript cell when the selected tool is `javascript`.
One cell can contain several side effects.
This callback therefore does not approve each browser action separately.

Application-defined tools can expose narrower approved operations.
Bind durable approvals to the action, arguments, target, run, and expiry.
Reject missing, failed, cancelled, or timed-out approvals.
Observation callbacks cannot approve an action.

## Trusted setup

A trusted application can execute setup before a task.
Browser-ready callbacks support deterministic setup after connection.
Initialization scripts apply before later document code where the selected target supports them.
Setup must not contain secret values that the model can read.

Apply required initialization before exposing new targets.
Define reconnect behavior explicitly.
Do not repeat a non-idempotent setup action automatically.

CDP observation callbacks must preserve policy listeners.
Passive observers provide diagnostics.
They do not enforce a security policy.

## Authentication and files

Connection authentication must cover endpoint discovery and the WebSocket handshake.
TLS verification remains enabled.
Custom certificate authorities and client certificates support private deployments.
Never upload credentials or endpoint tokens through product telemetry.

Remote browsers cannot read application-host file paths.
Uploads require actual transfer bytes and browser-visible staging.
Downloads require completion checks and retrieval into the application workspace.
Provider adapters preserve file grants and ownership rules.
The base agent exposes raw browser operations without a portable remote download helper.
Remote file workflows require explicit byte transfer or a provider API.

## Logs and recordings

Use `log="pretty"` for readable progress.
Use `log="json"` for structured progress.
Use event streams for application observers.

Keep task evidence in application-controlled storage.
Product telemetry uses a separate bounded field contract.
Keep raw exception text outside that product contract.

Recording captures sampled screenshots.
It does not prove every browser effect.
Recording failures must remain separate from task results.
Redact configured secret values from recording metadata.
Text redaction and export masks do not remove private pixels from raw captures.

## Deliberate omissions

The base package includes no vault, distributed scheduler, approval inbox, or audit-storage service.
It includes no operating-system sandbox or browser-side CDP firewall.
Applications and browser providers own those boundaries.
Keep unsupported controls out of the public API instead of claiming incomplete protection.
