#!/usr/bin/env python
"""Payer-wallet helper for the x402 rail (Stage 2 / WP-F, spec S10).

Two subcommands, both deliberately minimal:

    python scripts/x402_wallet.py new [--write-env PATH] [--force]
    python scripts/x402_wallet.py balance [ADDRESS]

────────────────────────────────────────────────────────────────────────────
WHY `new` NEVER PRINTS THE KEY
────────────────────────────────────────────────────────────────────────────
A private key printed to stdout ends up in the terminal scrollback, in the
shell's session log, in a CI job's artefacts and — in this project's case — in
an agent transcript. So `new` prints the ADDRESS and the names of the two
`.env` lines to fill, and nothing else. The generated key is either written
straight into a 0600 file (`--write-env`) or discarded.

Without `--write-env` the key really is thrown away: the command then only
tells you the address a key WOULD have had, which is not useful on its own.
That is the trade the spec asks for — the useful form is:

    python scripts/x402_wallet.py new --write-env .env

`balance` is read-only: one `eth_call` to `balanceOf` and one
`eth_getBalance`. It never needs a key; give it an address, or let it read
`X402_PAYER_ADDRESS` from the environment / `.env`. As a last resort it will
derive the address from `X402_PAYER_PRIVATE_KEY` — an address is public, the
key it came from is never shown.

Funding is a human step: EIP-3009 is gasless for the signer (the facilitator
broadcasts and pays gas), so the payer needs USDC and NOT Base Sepolia ETH.
When the USDC balance is zero this prints the faucet instruction.
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

# ---------------------------------------------------------------------------
# Constants. Imported from the gate so this script can never quote a different
# network / token than the one the 402 advertises and the payer signs.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.services.x402_gate import (  # noqa: E402
    DEFAULT_NETWORK,
    DEFAULT_USDC_ADDRESS,
    USDC_DECIMALS,
)
from app.services.x402_settlement import DEFAULT_RPC_URL  # noqa: E402

KEY_ENV = "X402_PAYER_PRIVATE_KEY"
ADDRESS_ENV = "X402_PAYER_ADDRESS"
RPC_ENV = "X402_RPC_URL"
USDC_ENV = "X402_USDC_ADDRESS"

FAUCET_URL = "https://faucet.circle.com"
FAUCET_HINT = (
    f"USDC balance is 0. Fund this address at {FAUCET_URL}\n"
    "  network: Base Sepolia   token: USDC   (20 USDC per address per 2 hours)\n"
    "  No Base Sepolia ETH is needed: EIP-3009 is gasless for the signer — the\n"
    "  facilitator broadcasts transferWithAuthorization and pays the gas."
)

# Minimal ERC-20 read ABI. Only the two views this script calls.
ERC20_READ_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class WalletRefusal(Exception):
    """A refusal the operator has to resolve; never a stack trace."""


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_x402_scripts.py)
# ---------------------------------------------------------------------------

def format_units(atomic: int, decimals: int) -> str:
    """Atomic units -> a decimal string. Exact; no float ever touches this."""
    return str(Decimal(atomic) / (Decimal(10) ** decimals))


def env_lines(private_key: str, address: str) -> str:
    """The exact two lines `--write-env` appends. One trailing newline."""
    return f"{KEY_ENV}={private_key}\n{ADDRESS_ENV}={address}\n"


def env_file_has_key(path: str) -> bool:
    """True when `path` already assigns KEY_ENV (so we refuse to append)."""
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.lstrip().startswith(f"{KEY_ENV}="):
                return True
    return False


def append_env_file(path: str, private_key: str, address: str) -> None:
    """Append the two lines with the file at mode 0600.

    `os.open` with 0o600 sets the mode only when the file is CREATED, so an
    existing file is chmod'ed as well — a key must not land in a world-readable
    file because the operator happened to have one lying around.
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        raise WalletRefusal(f"directory does not exist: {directory}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, env_lines(private_key, address).encode("utf-8"))
    finally:
        os.close(fd)


def resolve_address(explicit: str | None, environ: dict | None = None) -> str:
    """Which address `balance` reports on.

    Order: the CLI argument, then `X402_PAYER_ADDRESS`, then the address
    derived from `X402_PAYER_PRIVATE_KEY`. The key is read but never shown and
    never returned.
    """
    environ = os.environ if environ is None else environ
    if explicit:
        return explicit
    from_env = (environ.get(ADDRESS_ENV) or "").strip()
    if from_env:
        return from_env
    key = (environ.get(KEY_ENV) or "").strip()
    if key:
        from app.services.x402_payer import payer_address

        return payer_address(key)
    raise WalletRefusal(
        f"no address given: pass one as an argument, or set {ADDRESS_ENV} "
        f"(or {KEY_ENV}) in your environment / .env"
    )


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_new(args, *, out=print, account_factory=None) -> int:
    """Generate a payer key. Prints the address; never the key."""
    if account_factory is None:
        from eth_account import Account

        account_factory = Account.create
    account = account_factory()
    private_key = account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    address = account.address

    if args.write_env:
        if env_file_has_key(args.write_env) and not args.force:
            raise WalletRefusal(
                f"{args.write_env} already sets {KEY_ENV}; refusing to append a "
                "second one (dotenv would silently pick the last). Remove the "
                "existing line first, or pass --force if you meant to shadow it."
            )
        append_env_file(args.write_env, private_key, address)
        out(f"address : {address}")
        out(f"written : {args.write_env} (mode 600) — {KEY_ENV} and {ADDRESS_ENV}")
    else:
        out(f"address : {address}")
        out("")
        out("The key was NOT printed and NOT saved — it is gone. Set these two")
        out("lines in your local .env (never committed):")
        out(f"    {KEY_ENV}=<the 0x-prefixed private key>")
        out(f"    {ADDRESS_ENV}=<the matching 0x address>")
        out("To have this command write them for you:")
        out(f"    python {os.path.relpath(__file__, _REPO_ROOT)} new --write-env .env")

    out("")
    out(f"Fund it with test USDC: {FAUCET_URL} (network Base Sepolia, token USDC).")
    out("No Base Sepolia ETH is required — the facilitator pays the gas.")
    return 0


def cmd_balance(args, *, out=print, w3=None) -> int:
    """Report the address's USDC and native balances on Base Sepolia."""
    address = resolve_address(args.address)
    rpc_url = os.getenv(RPC_ENV, DEFAULT_RPC_URL)
    usdc_address = os.getenv(USDC_ENV, DEFAULT_USDC_ADDRESS)
    network = os.getenv("X402_NETWORK", DEFAULT_NETWORK)

    from web3 import Web3

    if w3 is None:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))

    checksum = Web3.to_checksum_address(address)
    token = w3.eth.contract(
        address=Web3.to_checksum_address(usdc_address), abi=ERC20_READ_ABI
    )
    usdc_atomic = token.functions.balanceOf(checksum).call()
    decimals = token.functions.decimals().call()
    native_wei = w3.eth.get_balance(checksum)

    out(f"network  : {network}")
    out(f"rpc      : {rpc_url}")
    out(f"address  : {checksum}")
    out(f"USDC     : {format_units(usdc_atomic, decimals)} "
        f"({usdc_atomic} atomic, {decimals} decimals, {usdc_address})")
    out(f"native   : {format_units(native_wei, 18)} ETH ({native_wei} wei)")
    if decimals != USDC_DECIMALS:
        out(f"WARNING  : token reports {decimals} decimals, expected {USDC_DECIMALS}")
    if usdc_atomic == 0:
        out("")
        out(FAUCET_HINT)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="x402_wallet.py",
        description="Generate / inspect the x402 payer wallet (Base Sepolia).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="generate a payer key (never prints it)")
    new.add_argument(
        "--write-env", metavar="PATH", default=None,
        help=f"append {KEY_ENV}= and {ADDRESS_ENV}= to PATH, chmod 600",
    )
    new.add_argument(
        "--force", action="store_true",
        help=f"append even if PATH already sets {KEY_ENV}",
    )
    new.set_defaults(func=cmd_new)

    balance = sub.add_parser("balance", help="read USDC + native balance (read-only)")
    balance.add_argument(
        "address", nargs="?", default=None,
        help=f"address to inspect; defaults to {ADDRESS_ENV} from the environment",
    )
    balance.set_defaults(func=cmd_balance)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # .env is how this repo carries local secrets; load it so `balance` works
    # with no flags. load_dotenv never overrides an already-exported variable.
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
    try:
        return args.func(args)
    except WalletRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised by the live run
    raise SystemExit(main())
