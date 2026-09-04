# The first live x402 settlement on Base Sepolia

Stage 2 / WP-F, step 3. This file is the evidence for the claim
`docs/x402-settlement.md` and both READMEs now make: HireNet's x402 rail has
actually moved USDC on a public chain. Everything below is verbatim stdout from
the two runs, plus an independent on-chain check that reuses none of the code
that produced the payments.

Until this document existed, every x402 module in `app/services/` said in its
own docstring that nothing had been executed against a live facilitator. Those
notes are now historical: **two payments, 0.01 USDC each, both confirmed.**

| | |
|---|---|
| date | 2026-09-04 (UTC timestamps in the logs; the werkzeug access lines are local time, UTC+10) |
| network | Base Sepolia, `eip155:84532` (chain id confirmed `84532` by `eth_chainId`) |
| asset | USDC `0x036CbD53842c5426634e7929541eC2318f3dCF7e`, 6 decimals |
| facilitator | `https://x402.org/facilitator` (public, no API key) |
| RPC | `https://sepolia.base.org` |
| payer | `0xa426EA414B75dF9aa4c2EFC08B9033E2Ad62eEbd` |
| payee | `0x67489daD728247099AEA1BF2875347160528697e` (the owner's own wallet — the demo asset's `wallet_address`) |
| price | `price_amount = 1` cent → `10000` atomic USDC → 0.01 USDC per invocation |
| spent | 0.02 USDC total, two invocations |

## Transactions

| run | tx | block | explorer |
|---|---|---|---|
| `--mode direct` | `0x7f2ac5767f7199ebb60ef3be77846a098c1e843141cdb76506c29fcfda46685e` | 46377044 | https://sepolia.basescan.org/tx/0x7f2ac5767f7199ebb60ef3be77846a098c1e843141cdb76506c29fcfda46685e |
| `--mode pact` | `0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c` | 46377059 | https://sepolia.basescan.org/tx/0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c |

## Balances

| | payer | payee |
|---|---|---|
| before | 20 USDC (`20000000`) | 0 USDC (`0`) |
| after run 1 (direct) | 19.99 USDC (`19990000`) | 0.01 USDC (`10000`) |
| after run 2 (pact) | 19.98 USDC (`19980000`) | 0.02 USDC (`20000`) |

Exactly 0.01 USDC left the payer per run and exactly 0.01 USDC arrived at the
payee per run. The payer's native balance was **0 ETH before and after**: the
payer signs an off-chain EIP-3009 authorization and never sends a transaction.

## What the chain says about who paid gas

Both transactions were **sent by `0xd407e409E34E0b9afb99EcCeb609bDbcD5e7f1bf`**
to the USDC contract. That is the facilitator's relayer address — the same one
`GET https://x402.org/facilitator/supported` advertises under
`signers["eip155:*"]`, recorded in `scratchpad/stage2/00-research.md` §A.4
*before* any of this was built. The research prediction "the payer needs USDC,
not ETH" is now an observation, not an assumption.

## 1. `--mode direct` — mcp_client pays for one tool call

Command (the payee is passed in; the script refuses to invent one):

```
X402_E2E_PAYEE=0x67489daD728247099AEA1BF2875347160528697e \
  .venv-stage2/bin/python scripts/x402_e2e.py --mode direct
```

A `--dry-run` was executed first and confirmed the quote without signing
anything; the quote block below is byte-identical to the dry run's.

```text
==========================================================================
x402 end-to-end — mode=direct
==========================================================================
network      : eip155:84532
asset (USDC) : 0x036CbD53842c5426634e7929541eC2318f3dCF7e
facilitator  : https://x402.org/facilitator
rpc          : https://sepolia.base.org
payer        : 0xa426EA414B75dF9aa4c2EFC08B9033E2Ad62eEbd
payee        : 0x67489daD728247099AEA1BF2875347160528697e
price        : 0.01 USDC (10000 atomic, price_amount=1 cents)
--max-usdc   : 0.01 USDC (10000 atomic)
payer USDC   : 20 (20000000 atomic)
database     : /var/folders/t7/hwgl0lrs4q5dy4zh22hrl9z40000gn/T/hirenet-x402-e2e-ife9yqos.db
asset_id     : a8b36e99-f36b-419f-aa13-ed94c414e790
MCP server   : http://127.0.0.1:63532  (gate installed, tool 'generate_greeting')
127.0.0.1 - - [04/Sep/2026 21:46:13] "POST /mcp/tools/call HTTP/1.1" 402 -

[11:46:13] unpaid probe -> HTTP 402
402 quote (PAYMENT-REQUIRED, decoded):
{
  "scheme": "exact",
  "network": "eip155:84532",
  "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
  "amount": "10000",
  "payTo": "0x67489daD728247099AEA1BF2875347160528697e",
  "maxTimeoutSeconds": 300,
  "extra": {
    "name": "USDC",
    "version": "2"
  }
}
quote matches the seeded asset: network, asset, payTo and amount all as expected.

[11:46:13] calling the gated tool with the payer key set — this signs ONE authorization
127.0.0.1 - - [04/Sep/2026 21:46:13] "POST /mcp/tools/call HTTP/1.1" 402 -
127.0.0.1 - - [04/Sep/2026 21:46:14] "POST /mcp/tools/call HTTP/1.1" 200 -
[11:46:14] call_mcp_tool returned in 1.4s with status='ok'
{
  "status": "ok",
  "tool": "generate_greeting",
  "total": 3,
  "endpoint_url": "http://127.0.0.1:63532",
  "payment": {
    "method": "x402",
    "tx_hash": "0x7f2ac5767f7199ebb60ef3be77846a098c1e843141cdb76506c29fcfda46685e",
    "network": "eip155:84532",
    "payer": "0xa426EA414B75dF9aa4c2EFC08B9033E2Ad62eEbd",
    "payee": "0x67489daD728247099AEA1BF2875347160528697e",
    "amount_atomic": "10000",
    "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "settle_success": true
  }
}

tx_hash      : 0x7f2ac5767f7199ebb60ef3be77846a098c1e843141cdb76506c29fcfda46685e
network      : eip155:84532
payer        : 0xa426EA414B75dF9aa4c2EFC08B9033E2Ad62eEbd
payee        : 0x67489daD728247099AEA1BF2875347160528697e
amount       : 10000 atomic (0.01 USDC)
explorer     : https://sepolia.basescan.org/tx/0x7f2ac5767f7199ebb60ef3be77846a098c1e843141cdb76506c29fcfda46685e

[11:46:15] check_status -> settled
receipt      : status=1 block=46377044 gasUsed=102820
  USDC Transfer  from=0xa426ea414b75df9aa4c2efc08b9033e2ad62eebd  to=0x67489dad728247099aea1bf2875347160528697e  value=10000 (0.01 USDC)

SETTLED — the USDC transfer is confirmed on Base Sepolia.
```

Read that log in the order the protocol runs:

1. `POST /mcp/tools/call` with no payment header → **402**, and the decoded
   `PAYMENT-REQUIRED` carries exactly one option: our network, our USDC
   address, the creator's `payTo` and `10000` atomic units. The gate resolved
   `payTo` from the seeded `skill_assets.wallet_address` — no address is
   hardcoded anywhere on that path.
2. `call_mcp_tool` repeats the request with `PAYMENT-SIGNATURE`. The gate
   `/verify`s with the facilitator, runs the handler, `/settle`s, and answers
   **200** with `PAYMENT-RESPONSE`. Elapsed: **1.4 s** for the whole
   402 → sign → verify → tool → settle round trip.
3. `X402SettlementProvider.check_status` returned **SETTLED on the first poll**
   (the transaction was already mined by the time the settle response came
   back), and the receipt carries the expected `Transfer`.

## 2. `--mode pact` — the product path

```
X402_E2E_PAYEE=0x67489daD728247099AEA1BF2875347160528697e \
  .venv-stage2/bin/python scripts/x402_e2e.py --mode pact
```

```text
==========================================================================
x402 end-to-end — mode=pact
==========================================================================
network      : eip155:84532
asset (USDC) : 0x036CbD53842c5426634e7929541eC2318f3dCF7e
facilitator  : https://x402.org/facilitator
rpc          : https://sepolia.base.org
payer        : 0xa426EA414B75dF9aa4c2EFC08B9033E2Ad62eEbd
payee        : 0x67489daD728247099AEA1BF2875347160528697e
price        : 0.01 USDC (10000 atomic, price_amount=1 cents)
--max-usdc   : 0.01 USDC (10000 atomic)
payer USDC   : 19.99 (19990000 atomic)
database     : /var/folders/t7/hwgl0lrs4q5dy4zh22hrl9z40000gn/T/hirenet-x402-e2e-8hl3sa4k.db
asset_id     : fd6b6140-7dfe-4e71-a247-0294afbaaa77
MCP server   : http://127.0.0.1:63553  (gate installed, tool 'generate_greeting')
127.0.0.1 - - [04/Sep/2026 21:46:42] "POST /mcp/tools/call HTTP/1.1" 402 -

[11:46:42] unpaid probe -> HTTP 402
402 quote (PAYMENT-REQUIRED, decoded):
{
  "scheme": "exact",
  "network": "eip155:84532",
  "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
  "amount": "10000",
  "payTo": "0x67489daD728247099AEA1BF2875347160528697e",
  "maxTimeoutSeconds": 300,
  "extra": {
    "name": "USDC",
    "version": "2"
  }
}
quote matches the seeded asset: network, asset, payTo and amount all as expected.
provider     : x402
mcp timeout  : 120.0s (injected; shipped default is 5s)

[11:46:42] POST /api/pact/create
{
  "agent_name": "客服话术生成器",
  "amount": 0.01,
  "amount_cap": 0.01,
  "approval_method": null,
  "approved_at": null,
  "approved_by": null,
  "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
  "content_hash": "4033265d71bb21bc3ca5ea3728b3377775db7127fd368a5eee834bd0dfbdb70b",
  "created_at": "2026-09-04T11:46:42.396802+00:00",
  "creator_id": null,
  "currency": "USD",
  "expires_at": "2026-09-05T11:46:42.396752+00:00",
  "intent": "Run 客服话术生成器 for task x402-e2e-pact-9809f637",
  "pact_id": "pact-5d9d5c4dae8c",
  "payee": "0x67489daD728247099AEA1BF2875347160528697e",
  "status": "pending",
  "task_id": "x402-e2e-pact-9809f637"
}

[11:46:42] POST /api/pact/approve/pact-5d9d5c4dae8c

[11:46:42] POST /api/pact/settle/pact-5d9d5c4dae8c — this signs ONE authorization
127.0.0.1 - - [04/Sep/2026 21:46:42] "POST /mcp/tools/call HTTP/1.1" 402 -
127.0.0.1 - - [04/Sep/2026 21:46:44] "POST /mcp/tools/call HTTP/1.1" 200 -
[11:46:44] settle returned HTTP 200 in 2.1s
{
  "agent_name": "客服话术生成器",
  "amount": 0.01,
  "amount_cap": 0.01,
  "approval_method": "ui",
  "approved_at": "2026-09-04T11:46:42.401308+00:00",
  "approved_by": "phase1_stub_employer",
  "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
  "content_hash": "4033265d71bb21bc3ca5ea3728b3377775db7127fd368a5eee834bd0dfbdb70b",
  "created_at": "2026-09-04T11:46:42.396802+00:00",
  "creator_id": null,
  "currency": "USD",
  "expires_at": "2026-09-05T11:46:42.396752+00:00",
  "explorer_url": "https://sepolia.basescan.org/tx/0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c",
  "intent": "Run 客服话术生成器 for task x402-e2e-pact-9809f637",
  "mcp_result": {
    "endpoint_url": "http://127.0.0.1:63553",
    "payment": {
      "amount_atomic": "10000",
      "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
      "method": "x402",
      "network": "eip155:84532",
      "payee": "0x67489daD728247099AEA1BF2875347160528697e",
      "payer": "0xa426EA414B75dF9aa4c2EFC08B9033E2Ad62eEbd",
      "settle_success": true,
      "tx_hash": "0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c"
    },
    "preview": [
      "您好，欢迎光临！请问有什么可以帮您？",
      "亲，欢迎咨询，我是您的专属客服小助手~",
      "您好，今天想了解我们的哪款产品呢？",
      "欢迎光临本店！有任何问题随时告诉我哦。",
      "亲爱的顾客您好，我能为您做些什么？"
    ],
    "status": "ok",
    "tool": "generate_greeting",
    "total": 40
  },
  "pact_id": "pact-5d9d5c4dae8c",
  "payee": "0x67489daD728247099AEA1BF2875347160528697e",
  "royalty_splits": {
    "creator": {
      "amount": 0,
      "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
      "chain": null,
      "creator_id": "x402_e2e_creator",
      "currency": "USD"
    },
    "platform": {
      "amount": 1,
      "chain": null,
      "currency": "USD"
    },
    "tax": {
      "amount": 0,
      "chain": null,
      "currency": "USD"
    }
  },
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "settled_amount": 0.01,
  "status": "settled",
  "task_id": "x402-e2e-pact-9809f637",
  "tx_hash": "0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c"
}

tx_hash        : 0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c
explorer_url   : https://sepolia.basescan.org/tx/0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c
settled_amount : 0.01

agent_runs:
{
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "agent_name": "客服话术生成器",
  "caller_id": "phase1_stub_employer",
  "task_id": "x402-e2e-pact-9809f637",
  "input_tokens": null,
  "output_tokens": null,
  "llm_cost_usd": null,
  "time_ms": null,
  "success": 1,
  "asset_ids": "[\"fd6b6140-7dfe-4e71-a247-0294afbaaa77\"]",
  "royalty_splits": "{\"creator\": {\"creator_id\": \"x402_e2e_creator\", \"asset_id\": \"fd6b6140-7dfe-4e71-a247-0294afbaaa77\", \"amount\": 0, \"currency\": \"USD\", \"chain\": null}, \"platform\": {\"amount\": 1, \"currency\": \"USD\", \"chain\": null}, \"tax\": {\"amount\": 0, \"currency\": \"USD\", \"chain\": null}}",
  "charge_amount": 1,
  "charge_currency": "USD",
  "charge_chain": null,
  "payment_method": "on_chain",
  "settlement_status": "settling",
  "settlement_method": "x402",
  "tx_hash": "0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c",
  "settlement_meta": "{\"method\": \"x402\", \"tx_hash\": \"0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c\", \"network\": \"eip155:84532\", \"payer\": \"0xa426EA414B75dF9aa4c2EFC08B9033E2Ad62eEbd\", \"payee\": \"0x67489daD728247099AEA1BF2875347160528697e\", \"amount_atomic\": 10000, \"asset\": \"0x036CbD53842c5426634e7929541eC2318f3dCF7e\"}",
  "created_at": "2026-09-04T11:46:44.442016+00:00"
}
royalty_ledger:
{
  "id": "9dd84625-c86f-43c8-90fd-91890d9f34ef",
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "creator_id": "x402_e2e_creator",
  "payee_id": "x402_e2e_creator",
  "party": "creator",
  "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
  "amount": 0,
  "currency": "USD",
  "chain": null,
  "status": "settling",
  "settlement_method": "x402",
  "tx_hash": "0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c",
  "note": null,
  "created_at": "2026-09-04T11:46:44.442139+00:00"
}
{
  "id": "4a40db72-95b3-49e8-b1b9-0f5c116c353f",
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "creator_id": "x402_e2e_creator",
  "payee_id": "platform",
  "party": "platform",
  "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
  "amount": 1,
  "currency": "USD",
  "chain": null,
  "status": "accrued",
  "settlement_method": "x402-fee-receivable",
  "tx_hash": null,
  "note": "platform share is a receivable from the creator: x402 'exact' pays a single payee (0x67489daD728247099AEA1BF2875347160528697e), so tx 0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c on eip155:84532 moved the creator's share only. Not paid on-chain. Phase 4: splitter contract or a second transfer.",
  "created_at": "2026-09-04T11:46:44.442172+00:00"
}
{
  "id": "6cf4b165-6950-4706-a6b8-884c9fb6d409",
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "creator_id": "x402_e2e_creator",
  "payee_id": "tax",
  "party": "tax",
  "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
  "amount": 0,
  "currency": "USD",
  "chain": null,
  "status": "accrued",
  "settlement_method": "x402-fee-receivable",
  "tx_hash": null,
  "note": "tax share is a receivable from the creator: x402 'exact' pays a single payee (0x67489daD728247099AEA1BF2875347160528697e), so tx 0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c on eip155:84532 moved the creator's share only. Not paid on-chain. Phase 4: splitter contract or a second transfer.",
  "created_at": "2026-09-04T11:46:44.442197+00:00"
}

[11:46:44] polling GET /api/royalty/status/e95d9807-a45e-4a36-a80f-f772f63eda4f until settled
[11:46:44] settlement_status -> settled
{
  "charge_amount": 1,
  "charge_chain": null,
  "charge_currency": "USD",
  "explorer_url": "https://sepolia.basescan.org/tx/0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c",
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "settlement_method": "x402",
  "settlement_status": "settled",
  "tx_hash": "0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c"
}

royalty_ledger after confirmation:
{
  "id": "9dd84625-c86f-43c8-90fd-91890d9f34ef",
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "creator_id": "x402_e2e_creator",
  "payee_id": "x402_e2e_creator",
  "party": "creator",
  "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
  "amount": 0,
  "currency": "USD",
  "chain": null,
  "status": "settled",
  "settlement_method": "x402",
  "tx_hash": "0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c",
  "note": null,
  "created_at": "2026-09-04T11:46:44.442139+00:00"
}
{
  "id": "4a40db72-95b3-49e8-b1b9-0f5c116c353f",
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "creator_id": "x402_e2e_creator",
  "payee_id": "platform",
  "party": "platform",
  "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
  "amount": 1,
  "currency": "USD",
  "chain": null,
  "status": "accrued",
  "settlement_method": "x402-fee-receivable",
  "tx_hash": null,
  "note": "platform share is a receivable from the creator: x402 'exact' pays a single payee (0x67489daD728247099AEA1BF2875347160528697e), so tx 0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c on eip155:84532 moved the creator's share only. Not paid on-chain. Phase 4: splitter contract or a second transfer.",
  "created_at": "2026-09-04T11:46:44.442172+00:00"
}
{
  "id": "6cf4b165-6950-4706-a6b8-884c9fb6d409",
  "run_id": "e95d9807-a45e-4a36-a80f-f772f63eda4f",
  "creator_id": "x402_e2e_creator",
  "payee_id": "tax",
  "party": "tax",
  "asset_id": "fd6b6140-7dfe-4e71-a247-0294afbaaa77",
  "amount": 0,
  "currency": "USD",
  "chain": null,
  "status": "accrued",
  "settlement_method": "x402-fee-receivable",
  "tx_hash": null,
  "note": "tax share is a receivable from the creator: x402 'exact' pays a single payee (0x67489daD728247099AEA1BF2875347160528697e), so tx 0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c on eip155:84532 moved the creator's share only. Not paid on-chain. Phase 4: splitter contract or a second transfer.",
  "created_at": "2026-09-04T11:46:44.442197+00:00"
}
receipt      : status=1 block=46377059 gasUsed=85720
  USDC Transfer  from=0xa426ea414b75df9aa4c2efc08b9033e2ad62eebd  to=0x67489dad728247099aea1bf2875347160528697e  value=10000 (0.01 USDC)

SETTLED — the pact, the run and the creator's royalty row are all confirmed against Base Sepolia.
```

What that run proves about the ledger, in the order it happens:

* the pact is created with the AP2-shaped mandate fields — `intent`,
  `amount_cap`, `expires_at`, `payee` (resolved from the asset's
  `wallet_address`) and `content_hash` — then approved, then settled;
* `POST /api/pact/settle` **paid before it recorded**: the settle response
  carries `tx_hash`, `explorer_url` and `settled_amount`, and the
  `agent_runs` row is born `settlement_status = "settling"`,
  `settlement_method = "x402"` — never `accrued`, because the money had already
  moved when the row was written;
* `settlement_meta` holds the `(payee, amount_atomic)` pair the provider later
  verifies against — 10000 atomic to
  `0x67489daD728247099AEA1BF2875347160528697e`;
* the creator's `royalty_ledger` row carries the same method and hash and goes
  `settling → settled` on the first `GET /api/royalty/status/<run_id>`, which
  is the only path that flips it, and only under the x402 provider;
* the platform and tax rows stay **`accrued` / `x402-fee-receivable`** with the
  note explaining why. This is the documented single-payee limitation: the
  `exact` scheme moved money to one address, so those two shares are
  receivables from the creator, not on-chain transfers. Nothing in this run
  pretends otherwise.

Settle took **2.1 s** end to end (402 → sign → verify → tool → settle → ledger
rows), and the status poll reached `settled` immediately after.

## 3. Independent verification

Re-derived from the chain alone, with a throwaway script that shares no code
with `scripts/x402_e2e.py` (plain `web3`, the topic0 constant typed out by
hand, receipts fetched fresh):

```text
chain_id: 84532

--- direct :: 0x7f2ac5767f7199ebb60ef3be77846a098c1e843141cdb76506c29fcfda46685e
  status      : 1
  block       : 46377044   gasUsed: 102820
  tx.from     : 0xd407e409E34E0b9afb99EcCeb609bDbcD5e7f1bf   (the facilitator relayer, pays gas)
  tx.to       : 0x036CbD53842c5426634e7929541eC2318f3dCF7e
  USDC Transfer from=0xa426ea414b75df9aa4c2efc08b9033e2ad62eebd to=0x67489dad728247099aea1bf2875347160528697e value=10000
    from == payer : True
    to   == payee : True
    value == 10000: True

--- pact :: 0x7f429da869579c9482bf09d6641161bed64b5e0d0f86f33d157334d978dc877c
  status      : 1
  block       : 46377059   gasUsed: 85720
  tx.from     : 0xd407e409E34E0b9afb99EcCeb609bDbcD5e7f1bf   (the facilitator relayer, pays gas)
  tx.to       : 0x036CbD53842c5426634e7929541eC2318f3dCF7e
  USDC Transfer from=0xa426ea414b75df9aa4c2efc08b9033e2ad62eebd to=0x67489dad728247099aea1bf2875347160528697e value=10000
    from == payer : True
    to   == payee : True
    value == 10000: True

final balances (atomic USDC)
  payer: 19980000
  payee: 20000
```

## 4. Observed, not fixed

Things this run surfaced. None of them is a defect introduced by WP-F, and none
was "fixed" by loosening a check.

* **A 1-cent charge splits degenerately.** `resolve_split` floors each share
  and hands the remainder to the platform (`RemainderStrategy.PLATFORM_ABSORBS`),
  so a 1-cent charge under a 70/20/10 rule becomes creator `0`, platform `1`,
  tax `0`. On the x402 rail the creator nevertheless received the **whole**
  0.01 USDC on-chain, so the ledger is internally coherent (the creator owes the
  platform that cent back as a receivable) but the creator's credit reads `0`
  next to a real payment. One cent is simply the smallest chargeable unit and
  the split has nothing to divide. Any demo price above a few cents behaves
  normally. Worth knowing before showing the ledger next to the explorer.
* **The MCP timeout — fixed in the route since this run.** At the time of the
  run above, `mcp_client`'s 5 s default governed the paid invocation and the
  pact route did not override it. Both live settles finished in ~1.5 s, so it
  did not bite — but a timeout on the *paid retry* is precisely
  `PaymentOutcomeUnknown`: an authorization on the wire with no answer, a pact
  frozen at `settling`, and a human reconciliation. The facilitator's own HTTP
  client allows 30 s per call (`verify` + `settle` = up to 60 s), so 5 s was the
  tightest link in the chain, and `scripts/x402_e2e.py --mode pact` injected a
  120 s client through the documented `MCP_CLIENT` seam — that injection was the
  **only** deviation from the shipped path in the run above (the payer, the
  gate, the facilitator, the recorder and the provider are all the real ones),
  and it is why the log line above reads `mcp timeout : 120.0s (injected…)`.
  **`_pact_settle_x402` now passes its own timeout**, `X402_PACT_INVOKE_TIMEOUT_S`,
  default **90 s** — the facilitator's 60 s pair with headroom — so the seam is
  no longer needed and the script injects nothing by default. `mcp_client`'s
  5 s default is unchanged and still governs every unpaid call, the legacy
  settle rail included.
* **`check_status` has no confirmation depth.** It returned SETTLED on a
  single-block-old receipt. Correct for a testnet demo; a mainnet deployment
  must wait for depth, as `SepoliaSettlementProvider` already can.

## 5. How to reproduce

```bash
cp /path/to/.env .env                        # X402_PAYER_PRIVATE_KEY lives here
.venv-stage2/bin/python scripts/x402_wallet.py balance          # expect >= 0.01 USDC
X402_E2E_PAYEE=0x… .venv-stage2/bin/python scripts/x402_e2e.py --mode direct --dry-run
X402_E2E_PAYEE=0x… .venv-stage2/bin/python scripts/x402_e2e.py --mode direct
X402_E2E_PAYEE=0x… .venv-stage2/bin/python scripts/x402_e2e.py --mode pact
```

Each non-dry invocation spends 0.01 USDC. See `docs/x402-settlement.md` for the
design, the environment variables and the known limitations.
