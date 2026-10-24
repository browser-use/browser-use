# Telemetry

The Pi emitter sends bounded usage metadata to EU PostHog ingestion when telemetry remains enabled.

Its strict field list excludes tasks, page content, outputs, secrets, raw errors, endpoint URLs, and configuration dumps.

Model identifiers can describe private deployments. The identifier check does not establish that an identifier is public.

Disable telemetry when your organization restricts those identifiers. Telemetry classification never requires catalog registration.

## Opt out

Python accepts telemetry=False. JavaScript accepts telemetry: false.

| Environment control       | Disable value      |
| ------------------------- | ------------------ |
| DO_NOT_TRACK              | 1                  |
| ANONYMIZED_TELEMETRY      | false, 0, no, off  |
| BH_TELEMETRY              | false, 0, no, off  |
| BROWSER_HARNESS_TELEMETRY | false, 0, no, off  |
| NODE_TEST_CONTEXT         | Any nonempty value |

False-value lists ignore case and surrounding spaces. Environment opt-outs override explicit enablement.

The emitter checks controls before creation and every send. Removing an opt-out does not reactivate an existing disabled reporter.

The CLI also supports its persisted Harness disable setting through browser-use telemetry disable.

Optional SDK telemetry does not control required Cloud service records.

## Ownership and identity

The event names are bu_operation_started and bu_operation_finished.

The operation_kind values are agent_run, browser_session, and cli_command.

One reporter uses one random session identifier. It does not count installations, people, or companies.

The Pi engine owns agent-run events. Wrappers supply client metadata.

Browser-only adapters can use this contract without a model. Their model usage remains unknown.

Controller identifies who requests browser work. Backend identifies the implementation.

Controllers include pi, openai_toolset, anthropic_toolset, cli_direct, and custom.

Backends include pi_runtime, browser_harness, and unknown.

Keep CLI invocation counts, browser-session counts, and agent-run counts separate.

## Common properties

Every event contains these properties:

| Group                 | Exact fields                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------------- |
| Contract              | schema_version, measurement_version                                                                 |
| Identity              | distinct_id, session_id, event_id, operation_id, parent_operation_id, child_id                      |
| Operation             | operation_kind, aggregation, sampling_probability, subagent_tracking                                |
| Privacy               | $process_person_profile, $geoip_disable                                                             |
| Host runtime          | os, architecture, runtime, runtime_version, docker, docker_detection                                |
| Versions              | engine_version, client_version                                                                      |
| Attribution           | client_language, entrypoint, controller, backend                                                    |
| Browser configuration | browser_requested, browser_selection, cdp_protocol, cdp_endpoint_category                           |
| Model                 | model_id, model_provider, model_api, model_context_window, model_max_output_tokens                  |
| Model capabilities    | model_reasoning, model_image_input, model_metadata_source                                           |
| Pricing               | pricing_known, pricing_unit, pricing_input, pricing_output, pricing_cache_read, pricing_cache_write |

Schema and measurement versions currently equal 1. Sampling probability currently equals 1.

The reporter disables person profiles and GeoIP enrichment. It sends no IP property.

IP means Internet Protocol, the address system for network connections. The ingestion service still receives each network request.

Distinct identity equals the session identifier. Optional parent and child identifiers accept UUIDs only.

A UUID is a randomly generated identifier. Invalid supplied identifiers become null.

Aggregation uses direct or cumulative_rollup. The reporter never adds parent or child usage automatically.

Subagent tracking currently reports unsupported. Parent identifiers provide correlation without proving complete descendant accounting.

Version fields use supplied versions or package metadata. Missing versions remain unknown or null.

Installation source accepts wheel, editable, git, or unknown. A wheel does not reveal whether pip or uv installed it.

Runtime fields describe the agent host. They do not describe a remote browser host.

Docker detection returns true when a Docker marker or Docker cgroup text exists.

A cgroup is a Linux resource-control group. The emitter sends no cgroup path.

Linux checks without positive evidence return null. The detector returns false on macOS and null for other uncertain platforms.

Detection method uses platform, marker, cgroup, or unknown.

The emitter collects no CPU profile, memory profile, installed-package inventory, hostname, or hardware fingerprint.

CPU means processor use.

## Browser and model categories

Browser requested accepts cloud, cdp, chrome, chromium, pending, or unknown.

Browser selection accepts default, explicit, or unknown.

CDP protocol accepts ws, wss, http, https, unknown, or null.

CDP means Chrome DevTools Protocol, Chrome's browser control connection.

CDP endpoint category accepts loopback, private, public, hostname, or unknown.

The classifier checks the supplied endpoint locally. It performs no DNS lookup.

DNS translates hostnames into network addresses.

The payload excludes endpoint URLs, hostnames, addresses, paths, credentials, and authentication headers.

Endpoint category does not establish browser location. A loopback tunnel can reach a remote browser.

A CDP label does not establish Cloud use. Cloud adoption requires explicit provisioning or execution evidence.

Model identifiers use at most 200 characters. URL-shaped values and unsupported characters become null.

The serializer sends no model headers, compatibility maps, endpoint values, or model object.

Model metadata source accepts catalog, explicit, template, discovery, or unknown.

Provider identity describes configuration. It does not independently attest model authorship or backend routing.

Pricing fields use USD per million tokens. Rates require an explicit pricing-known state.

Unknown prices produce null estimated costs. They never produce fake zero-dollar estimates.

Cost fields describe model estimates. They exclude remote browser charges and external service charges.

## Start properties

Start events add these properties:

| Group                 | Exact fields                                                 |
| --------------------- | ------------------------------------------------------------ |
| Feature configuration | configured_features                                          |
| Budgets               | max_steps, timeout_ms, max_cost_usd, max_context_chars       |
| Run features          | compaction_enabled, structured_output                        |
| Run callbacks         | event_callback, observer_callback, context_recovery_callback |

Configured features contain only:

| Group     | Exact fields                                                                                |
| --------- | ------------------------------------------------------------------------------------------- |
| Agent     | mode, reasoning, research_tools                                                             |
| Browser   | browser_switching, dedicated_browser, focus_tab, action_highlights, init_scripts_configured |
| Policy    | allowlist_configured, denylist_configured, secrets_configured, redaction_configured         |
| Tools     | custom_tools_configured                                                                     |
| Callbacks | before_tool_callback, after_tool_callback, validator_callback, browser_ready_callback       |
| Records   | log_format, history_restore, recording_configured                                           |
| Search    | search_configured                                                                           |

Missing measurements remain null or unknown. Configuration does not establish actual use.

These fields use booleans and fixed categories. They exclude domain lists, secret names, tool names, schemas, and callback content.

## Finish properties

Finish events add these properties:

| Group             | Exact fields                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------- |
| Outcome           | status, error_class, error_stage, task_verification                                                     |
| Time              | operation_duration_ms, run_duration_ms, paused_duration_ms, model_duration_ms_sum, tool_duration_ms_sum |
| Browser execution | browser_effective                                                                                       |
| Feature execution | feature_usage, feature_coverage                                                                         |
| Loop              | steps, provider_retries, finish_repairs                                                                 |
| Context           | compactions, compaction_failures, compaction_failure_class, context_chars, context_tokens_estimated     |
| Usage             | usage, summary_usage, usage_completeness, cost_completeness, usage_scope, descendant_usage              |

Status accepts completed, max_steps, timeout, cancelled, cost_limit, context_limit, incomplete, error, or closed.

Task verification currently reports unknown. Completion does not independently prove task success.

Error class accepts configuration, authentication, provisioning, connection, policy, model, tool, validation, persistence, cleanup, cancelled, unknown, or null.

Error stage accepts startup, configure, provision, connect, model, tool, persist, cleanup, or null.

The reporter excludes exception messages and stack traces.

Operation duration uses a monotonic clock. Result-provided run duration follows the result's measurement method.

Paused time measures acknowledged pause intervals when instrumentation supplies it. Missing timing measurements remain null.

Model and tool intervals can overlap. Their sums do not equal wall time.

Current assistant-message timing can omit model connection setup, summary requests, and interrupted responses.

Context token measurements use estimates. They do not establish provider billing tokens.

### Usage objects

Usage and summary_usage contain input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, total_tokens, and estimated_cost_usd.

Summary usage forms part of inclusive run usage. Never add that subtotal to the run total.

The reporter accepts a separate summary subtotal when instrumentation supplies it. Missing subtotals remain null.

Unknown, negative, and nonfinite numbers become null.

Usage completeness and cost completeness accept complete, partial, or unknown.

Complete means complete within the measurement scope. Provider deadlines can hide usage and billing information.

Missing pricing or invalid cost totals prevent complete cost claims.

Usage scope uses direct_including_summary_and_retries for direct events. Rollups use cumulative_rollup.

Descendant usage currently remains null. External work needs explicit instrumentation before the reporter can attribute its usage.

Never add cumulative rollups to child totals. Sum direct usage across unique operations, including parents with direct model work.

### Feature counters

Feature usage contains only:

| Group       | Exact counters                                                        |
| ----------- | --------------------------------------------------------------------- |
| Tools       | tool_calls, tool_errors                                               |
| Callbacks   | callback_calls, callback_errors, callback_timeouts                    |
| Controls    | pause_requests, pauses, resumes, steering_accepted, steering_consumed |
| Connections | connections, reconnects, browser_switches                             |
| Domains     | domain_checks, domain_denials                                         |
| Secrets     | secret_attempts, secret_insertions                                    |
| Files       | uploads, downloads                                                    |
| Records     | recordings_saved, history_saved                                       |
| Output      | schema_rejections, validator_calls, validator_rejections              |

Unmeasured counters remain null. Explicitly observed zero differs from unknown.

Feature coverage accepts complete, partial, unknown, or unsupported. Its default remains partial.

Raw CDP and arbitrary JavaScript can bypass semantic counters. Missing observations do not establish absent feature adoption.

## Delivery and analysis limits

Each operation reserves bounded capacity for its start and finish. The reporter permits at most 32 pending or reserved sends.

When capacity fills, it omits another operation's pair. Network failures can still lose either event.

Each request uses a one-second timeout without retries. A manual flush waits at most 1.1 seconds.

Transport failures do not change operation results. Repeated finish calls send no duplicate terminal event.

Deduplicate received events by event_id. Correlate phases through operation_id.

Missing finishes mean unknown outcomes. They do not prove crashes or task failures.

Received telemetry-enabled operations define all denominators. They do not represent every installation, user, or run.

Count configured share among eligible starts with known configuration. Count used share among finishes with complete relevant coverage.

Show missing outcomes, unknown configuration, and partial coverage beside every usage rate.

Browser Use suppresses the legacy Harness emitter for direct CLI programs and direct MCP sessions.

Their child daemons inherit this suppression. These direct paths currently send no product telemetry.

Pi task commands retain the bounded Pi emitter. Telemetry settings commands retain their stored preferences.

The independent browser-harness command keeps its existing telemetry defaults.

Browser-only adapters cannot infer an external runner's models, tokens, compactions, costs, or final task outcome.
