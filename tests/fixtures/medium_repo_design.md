# Medium Fixture Repository Design

## Purpose

`medium_repo` is a planned fixture repository for evaluating CodeTeam beyond the current small smoke fixture at `tests/fixtures/test_repo`.

The current `test_repo` should remain small and predictable. Its job is to verify that scanner, parser, import extraction, ranking, context building, and eval commands can run end to end.

`medium_repo` should instead expose realistic retrieval and context-building failure modes:

- Chinese natural-language queries that need English code signal expansion.
- SymbolIndex gains that are not reducible to direct ripgrep matches.
- ImportGraph gains where a seed file should expand to required related files.
- Non-Python instruction/config/documentation recall.
- Generated/vendor/test/config ranking behavior.
- Context compression under realistic file sizes.
- Partial indexing when a file is syntactically broken or unsupported.

This fixture is not meant to be a real application. It is a controlled benchmark target with enough complexity to reveal system weaknesses while keeping gold labels auditable.

## Design Principles

1. Keep `test_repo` small and keep `medium_repo` separate.
2. Do not paste evaluation query sentences directly into gold files.
3. Gold files must be determined from repository semantics, not from system output.
4. Each eval case should have a `gold_rationale`.
5. Required gold files should stay within 1-5 files for Recall@5.
6. Include both easy cases and hard cases, but label the intended capability.
7. Avoid making every case solvable by exact text search.
8. Include failure-tolerant files: broken Python, large generated code, and non-Python config.

## Target Size

Approximate target:

- 60-90 files total.
- 35-55 Python source/test files.
- 10-15 docs/config/instruction files.
- 5-10 generated/vendor/noise files.
- 6-8 business modules.
- 25-40 eval cases.

The fixture should stay small enough that eval runs quickly, but large enough that Top 5 retrieval is meaningful.

## Proposed Directory Layout

```text
tests/fixtures/medium_repo/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── configs/
│   ├── feature_flags.yaml
│   ├── logging.yaml
│   └── retry_policy.toml
├── docs/
│   ├── auth.md
│   ├── billing.md
│   ├── orders.md
│   ├── inventory.md
│   └── generated-code-policy.md
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── auth/
│   │   ├── AGENTS.md
│   │   ├── __init__.py
│   │   ├── api.py
│   │   ├── exceptions.py
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── tokens.py
│   ├── billing/
│   │   ├── __init__.py
│   │   ├── invoices.py
│   │   ├── payment_gateway.py
│   │   ├── retries.py
│   │   └── webhooks.py
│   ├── orders/
│   │   ├── AGENTS.md
│   │   ├── __init__.py
│   │   ├── api.py
│   │   ├── events.py
│   │   ├── exporter.py
│   │   ├── service.py
│   │   └── worker.py
│   ├── inventory/
│   │   ├── __init__.py
│   │   ├── allocator.py
│   │   ├── reservations.py
│   │   └── service.py
│   ├── notifications/
│   │   ├── __init__.py
│   │   ├── email.py
│   │   ├── templates.py
│   │   └── dispatcher.py
│   ├── common/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── events.py
│   │   ├── logging.py
│   │   ├── settings.py
│   │   └── time.py
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── loader.py
│   │   └── fraud_rules.py
│   ├── generated/
│   │   ├── __init__.py
│   │   ├── openapi_client.py
│   │   └── billing_schema.py
│   └── experimental/
│       ├── __init__.py
│       └── broken_parser_case.py
├── tests/
│   ├── __init__.py
│   ├── auth/
│   │   ├── test_refresh_flow.py
│   │   └── test_token_repository.py
│   ├── billing/
│   │   ├── test_invoice_retry.py
│   │   └── test_webhook_signature.py
│   ├── orders/
│   │   ├── test_order_cancel.py
│   │   └── test_order_export.py
│   └── inventory/
│       └── test_reservations.py
├── vendor/
│   └── third_party_payment.py
```

The retrieval dataset intentionally lives outside the fixture repository at
`evals/medium_repo/file_retrieval.jsonl` so scanner/ripgrep/candidate
generation do not retrieve the benchmark file itself.

## Module Semantics

### Auth

Purpose: token refresh, token repository, API error mapping.

Important relationships:

- `auth/api.py` calls `AuthService.refresh_session`.
- `auth/service.py` validates refresh tokens using `auth/tokens.py`.
- `auth/service.py` reads and writes token records through `auth/repository.py`.
- `auth/exceptions.py` defines API-facing token errors.
- `tests/auth/test_refresh_flow.py` verifies expired refresh tokens map to 401-like errors.

Hard retrieval targets:

- Chinese query "刷新登录状态过期后为什么返回 500" should require `auth/service.py`, `auth/api.py`, `auth/exceptions.py`, and `tests/auth/test_refresh_flow.py`.
- Query mentions behavior, not exact `refresh_session`.

### Orders

Purpose: order creation, cancellation, export, worker processing.

Important relationships:

- `orders/api.py` calls `orders/service.py`.
- `orders/service.py` emits domain events through `common/events.py`.
- `orders/worker.py` consumes order events and calls `inventory/service.py`.
- `orders/exporter.py` streams order export rather than loading all rows.
- `orders/AGENTS.md` contains module-specific testing rules.

Hard retrieval targets:

- Chinese query "取消订单后库存预占没有释放" should require `orders/service.py`, `inventory/reservations.py`, `inventory/service.py`, and `tests/orders/test_order_cancel.py`.
- Query should not directly include function names like `release_inventory_hold`.

### Inventory

Purpose: stock allocation and reservation lifecycle.

Important relationships:

- `inventory/allocator.py` has allocation symbols.
- `inventory/reservations.py` owns reservation state transitions.
- `inventory/service.py` is the facade called by orders.

Hard retrieval targets:

- Symbol-only query should locate definitions.
- Cross-module query should need both orders and inventory files.

### Billing

Purpose: payment webhooks, invoice retry, payment gateway abstraction.

Important relationships:

- `billing/webhooks.py` validates provider signatures.
- `billing/retries.py` loads retry rules from `configs/retry_policy.toml`.
- `billing/payment_gateway.py` imports a vendor-like provider.
- `billing/invoices.py` uses common database and time utilities.

Hard retrieval targets:

- Query "支付回调签名验证失败" should find `billing/webhooks.py`, `billing/payment_gateway.py`, and `tests/billing/test_webhook_signature.py`.
- Query "发票重试间隔在哪里配置" should recall `configs/retry_policy.toml` and `billing/retries.py`.

### Notifications

Purpose: email templates and event-driven dispatch.

Important relationships:

- `notifications/dispatcher.py` listens to domain events.
- `notifications/templates.py` stores template keys.
- `notifications/email.py` performs sending.

Hard retrieval targets:

- Query should test ImportGraph from event producer to notification consumer.

### Common

Purpose: shared database/session, events, logging, settings.

Important relationships:

- `common/database.py` should be a frequent dependency.
- `common/events.py` defines event bus and event names.
- `common/settings.py` reads YAML/TOML config.

Hard retrieval targets:

- Cross-module "which files use database session factory" query should require several dependents.

### Plugins

Purpose: dynamic import and static analysis limitations.

Important relationships:

- `plugins/loader.py` uses `importlib.import_module`.
- `plugins/fraud_rules.py` is a possible plugin target.

Hard retrieval targets:

- Dynamic import should be marked as dynamic/unresolved but should not crash indexing.

### Generated and Vendor

Purpose: ranking penalties and noise.

Important relationships:

- `generated/openapi_client.py` and `generated/billing_schema.py` should contain many classes/functions.
- `vendor/third_party_payment.py` should look useful but should be deprioritized.

Hard retrieval targets:

- Query about generated code policy should recall `docs/generated-code-policy.md` or `AGENTS.md`, not dump generated source unless explicitly needed.

### Experimental Broken File

Purpose: failure tolerance.

Important relationships:

- `experimental/broken_parser_case.py` contains a syntax error.

Expected behavior:

- `inspect-repo` should report a failed/partial parse warning.
- `context` and `eval` should continue and surface diagnostics.

## Instruction Files

### Root AGENTS.md

Should include:

- General commands:
  - `uv run pytest tests/ -q`
  - `uv run ruff check src tests`
  - `uv run mypy src`
- Safety rules:
  - Do not modify `src/generated/`.
  - Do not edit vendor code.
  - Database migrations require approval.
- Architecture rules:
  - API files should not execute SQL directly.
  - Business logic belongs in service modules.
  - Shared event names belong in `src/common/events.py`.

### Nested AGENTS.md

`src/auth/AGENTS.md`:

- Token-related tests live under `tests/auth/`.
- Auth errors should be mapped at API boundary.

`src/orders/AGENTS.md`:

- Order cancellation must update inventory reservations.
- Export tests live under `tests/orders/test_order_export.py`.

Expected behavior:

- `context` should load root + relevant nested AGENTS for target files.
- Command detection should preserve explicit commands from AGENTS.

## Evaluation Dataset Plan

Create:

```text
evals/medium_repo/file_retrieval.jsonl
```

Keep `tests/fixtures/medium_repo/` as the repository under evaluation only.
Do not place eval JSONL files inside the fixture tree; otherwise retrieval can
return `evals/file_retrieval.jsonl` as a candidate and pollute the benchmark.

### Categories

Use 30 cases:

- 5 exact symbol cases.
- 5 error/config string cases.
- 6 Chinese business behavior cases.
- 5 cross-module/import graph cases.
- 4 instruction/config/docs cases.
- 3 generated/vendor/noise cases.
- 2 parser/failure-diagnostic cases.

### Example Cases

These are examples of query intent, not final exact JSONL rows.

#### SymbolIndex-Oriented

1. Query: `Find InventoryReservationStore.mark_released`
   - Gold: `src/inventory/reservations.py`
   - Purpose: exact symbol.

2. Query: `Where is PaymentWebhookVerifier defined?`
   - Gold: `src/billing/webhooks.py`
   - Purpose: class symbol.

3. Query: `Which file defines EventEnvelope?`
   - Gold: `src/common/events.py`
   - Purpose: shared symbol.

#### ImportGraph-Oriented

4. Query: `订单取消后库存释放链路`
   - Gold: `src/orders/service.py`, `src/inventory/service.py`, `src/inventory/reservations.py`, `tests/orders/test_order_cancel.py`
   - Purpose: Chinese query + cross-module graph.

5. Query: `payment webhook creates invoice retry event`
   - Gold: `src/billing/webhooks.py`, `src/billing/retries.py`, `src/common/events.py`
   - Purpose: event flow.

6. Query: `database session factory usage across business modules`
   - Gold: `src/common/database.py`, `src/auth/repository.py`, `src/orders/exporter.py`, `src/billing/invoices.py`
   - Purpose: dependents.

#### Chinese Business Queries

7. Query: `刷新登录状态过期后接口不应该返回 500`
   - Gold: `src/auth/service.py`, `src/auth/api.py`, `src/auth/exceptions.py`, `tests/auth/test_refresh_flow.py`
   - Purpose: Chinese to English domain expansion.

8. Query: `取消订单后库存预占没有释放`
   - Gold: `src/orders/service.py`, `src/inventory/reservations.py`, `tests/orders/test_order_cancel.py`
   - Purpose: Chinese phrase mapping.

9. Query: `发票重试间隔配置在哪里`
   - Gold: `configs/retry_policy.toml`, `src/billing/retries.py`
   - Purpose: config + code.

#### Non-Python Instruction/Config

10. Query: `生成代码不能手动修改的规则在哪里`
    - Gold: `AGENTS.md`, `docs/generated-code-policy.md`
    - Purpose: instruction/docs recall.

11. Query: `订单模块的专用测试命令写在哪里`
    - Gold: `src/orders/AGENTS.md`
    - Purpose: nested AGENTS.

12. Query: `pytest 默认测试路径在哪里配置`
    - Gold: `pyproject.toml`
    - Purpose: TOML config.

#### Generated/Vendor Noise

13. Query: `OpenAPI generated client has many classes and should be deprioritized`
    - Gold: `src/generated/openapi_client.py`, `docs/generated-code-policy.md`
    - Purpose: generated detection.

14. Query: `third party payment provider timeout`
    - Gold: `src/billing/payment_gateway.py`, `vendor/third_party_payment.py`
    - Purpose: vendor relation without over-ranking vendor.

#### Failure Diagnostics

15. Query: `experimental parser failure should not stop indexing`
    - Gold: `src/experimental/broken_parser_case.py`
    - Purpose: diagnostics visibility.

## Anti-Leakage Rules

When creating files:

- Do not copy final Chinese query sentences verbatim into source/doc files.
- Use realistic code names and comments, not eval labels.
- Avoid placing all gold clues in docstrings.
- Keep some gold files discoverable only through imports or symbols.
- Freeze gold labels before running eval.

When creating eval rows:

- Include `gold_rationale`.
- Include `supporting_files` for helpful but non-required files.
- Include `capability_target`, for example:
  - `symbol_index`
  - `import_graph`
  - `chinese_query_expansion`
  - `instruction_recall`
  - `generated_penalty`
  - `diagnostics`

## Expected Baselines

The medium fixture should not be tuned so every method scores high.

Expected rough behavior before improvements:

```text
filename:        low to moderate
ripgrep:         moderate
ripgrep_symbol:  better on symbol cases
hybrid:          better on cross-module cases
```

If `ripgrep`, `ripgrep_symbol`, and `hybrid` tie again, the dataset likely still does not isolate SymbolIndex or ImportGraph.

## Validation Commands

After the fixture is implemented:

```bash
.venv/bin/python -m codeteam.cli.app inspect-repo tests/fixtures/medium_repo --format json

.venv/bin/python -m codeteam.cli.app context \
  "取消订单后库存预占没有释放" \
  --path tests/fixtures/medium_repo \
  --top-k 5 \
  --budget 1024 \
  --format json

.venv/bin/python -m codeteam.cli.app eval \
  --dataset evals/medium_repo/file_retrieval.jsonl \
  --repo tests/fixtures/medium_repo \
  --methods filename,ripgrep,ripgrep_symbol,hybrid \
  --output /tmp/codeteam-medium-eval
```

## Implementation Phases

### Phase 1: Skeleton

- Create directories and minimal files.
- Add root and nested AGENTS.
- Add pyproject and config files.
- Ensure scanner can inspect repo.

### Phase 2: Code Semantics

- Add auth/orders/inventory/billing/common modules.
- Add imports and cross-module flows.
- Add generated/vendor/experimental files.

### Phase 3: Eval Dataset

- Add 25-30 JSONL eval cases.
- Add rationales and capability targets.
- Run eval and record baseline.

### Phase 4: Review

- Check for query leakage.
- Check gold labels manually.
- Confirm ablation has discriminative power.
