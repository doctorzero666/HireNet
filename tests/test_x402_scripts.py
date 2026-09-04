"""Stage 2 / WP-F: unit tests for the two operator scripts.

Scope, stated plainly: these tests cover the scripts' PURE parts — argument
parsing, every refusal that must fire before anything is signed, the seeding
helper, the quote comparison, and the "never print the key" contract. Nothing
here contacts a facilitator, an RPC endpoint or a chain; the autouse guard
below fails the test if anything tries.

WHAT THESE TESTS DO NOT ESTABLISH: that `scripts/x402_e2e.py` can complete a
payment. That is what the live run in `docs/x402-first-run.md` is for — a green
suite here says the refusals work, not that the money moves.
"""
import os
import socket
import stat

import httpx
import pytest
import requests
from eth_account import Account

from app.services.x402_gate import (
    DEFAULT_NETWORK,
    DEFAULT_USDC_ADDRESS,
    asset_price_atomic,
)
from app.storage.db import init_db
from app.storage.skill_assets import get_skill_asset
from scripts import x402_e2e, x402_wallet
from tests.test_x402_payer import make_option

# A throwaway key that exists only in this file. It is NOT the operator's; the
# tests below assert it never reaches stdout, which is the actual contract.
FIXTURE_KEY = "0x" + "22" * 32
FIXTURE_ADDRESS = Account.from_key(FIXTURE_KEY).address

PAYEE = "0x67489daD728247099AEA1BF2875347160528697e"


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Fail loudly if a test would touch the network."""
    def _boom(*args, **kwargs):
        raise AssertionError("script unit tests must not make real network calls")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _boom)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _boom)
    monkeypatch.setattr(socket.socket, "connect", _boom)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Never inherit the operator's key, address or payee.

    Both scripts call `load_dotenv` on the repo's real `.env` in `main()`, and
    that file holds the operator's funded payer key. The `no_dotenv` fixture in
    tests/conftest.py neuters it suite-wide, so nothing here can read — or leak
    into `os.environ` — a machine-local secret.
    """
    for name in (x402_wallet.KEY_ENV, x402_wallet.ADDRESS_ENV,
                 x402_e2e.PAYEE_ENV, "X402_RPC_URL", "X402_USDC_ADDRESS",
                 "X402_NETWORK", "X402_FACILITATOR_URL"):
        monkeypatch.delenv(name, raising=False)


class Recorder:
    """Collects printed lines so a test can assert on what was NOT printed."""

    def __init__(self):
        self.lines = []

    def __call__(self, *parts):
        self.lines.append(" ".join(str(p) for p in parts))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class FakeCall:
    def __init__(self, value):
        self._value = value

    def call(self):
        return self._value


class FakeFunctions:
    def __init__(self, balance, decimals):
        self._balance = balance
        self._decimals = decimals

    def balanceOf(self, _address):  # noqa: N802 - mirrors the ERC-20 ABI name
        return FakeCall(self._balance)

    def decimals(self):
        return FakeCall(self._decimals)


class FakeContract:
    def __init__(self, balance, decimals):
        self.functions = FakeFunctions(balance, decimals)


class FakeEth:
    def __init__(self, balance, decimals, native):
        self._balance = balance
        self._decimals = decimals
        self._native = native

    def contract(self, address=None, abi=None):
        return FakeContract(self._balance, self._decimals)

    def get_balance(self, _address):
        return self._native


class FakeW3:
    """Enough of a Web3 handle for `balance`; dials nothing."""

    def __init__(self, balance=20_000_000, decimals=6, native=0):
        self.eth = FakeEth(balance, decimals, native)


# ===========================================================================
# scripts/x402_wallet.py
# ===========================================================================

def test_wallet_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        x402_wallet.build_parser().parse_args([])


def test_wallet_parser_reads_new_and_balance():
    parser = x402_wallet.build_parser()
    new = parser.parse_args(["new", "--write-env", ".env"])
    assert new.command == "new" and new.write_env == ".env" and new.force is False
    balance = parser.parse_args(["balance", FIXTURE_ADDRESS])
    assert balance.command == "balance" and balance.address == FIXTURE_ADDRESS
    assert parser.parse_args(["balance"]).address is None


def test_format_units_is_exact_not_float():
    # 0.1 + 0.2 style drift is exactly what a Decimal path must not produce.
    assert x402_wallet.format_units(20_000_000, 6) == "20"
    assert x402_wallet.format_units(1, 6) == "0.000001"
    assert x402_wallet.format_units(123_456_789, 6) == "123.456789"


def test_env_lines_names_both_variables_once():
    lines = x402_wallet.env_lines(FIXTURE_KEY, FIXTURE_ADDRESS)
    assert lines == (
        f"{x402_wallet.KEY_ENV}={FIXTURE_KEY}\n"
        f"{x402_wallet.ADDRESS_ENV}={FIXTURE_ADDRESS}\n"
    )


def test_new_without_write_env_prints_the_address_and_never_the_key():
    out = Recorder()
    args = x402_wallet.build_parser().parse_args(["new"])
    rc = x402_wallet.cmd_new(
        args, out=out, account_factory=lambda: Account.from_key(FIXTURE_KEY)
    )
    assert rc == 0
    assert FIXTURE_ADDRESS in out.text
    # The contract that matters: the key, in any casing, is absent.
    assert FIXTURE_KEY not in out.text
    assert FIXTURE_KEY[2:] not in out.text.lower()
    # It names the variables to set, without values.
    assert x402_wallet.KEY_ENV in out.text
    assert x402_wallet.ADDRESS_ENV in out.text


def test_new_with_write_env_writes_0600_and_still_prints_only_the_address(tmp_path):
    target = tmp_path / "env-file"
    out = Recorder()
    args = x402_wallet.build_parser().parse_args(["new", "--write-env", str(target)])
    rc = x402_wallet.cmd_new(
        args, out=out, account_factory=lambda: Account.from_key(FIXTURE_KEY)
    )
    assert rc == 0
    written = target.read_text()
    assert f"{x402_wallet.KEY_ENV}={FIXTURE_KEY}" in written
    assert f"{x402_wallet.ADDRESS_ENV}={FIXTURE_ADDRESS}" in written
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert FIXTURE_KEY not in out.text
    assert FIXTURE_ADDRESS in out.text


def test_write_env_tightens_the_mode_of_an_existing_loose_file(tmp_path):
    target = tmp_path / "env-file"
    target.write_text("OTHER=1\n")
    os.chmod(target, 0o644)
    args = x402_wallet.build_parser().parse_args(["new", "--write-env", str(target)])
    x402_wallet.cmd_new(
        args, out=Recorder(), account_factory=lambda: Account.from_key(FIXTURE_KEY)
    )
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600


def test_write_env_refuses_to_append_a_second_key(tmp_path):
    target = tmp_path / "env-file"
    target.write_text(f"{x402_wallet.KEY_ENV}=0xdead\n")
    args = x402_wallet.build_parser().parse_args(["new", "--write-env", str(target)])
    with pytest.raises(x402_wallet.WalletRefusal) as exc:
        x402_wallet.cmd_new(
            args, out=Recorder(), account_factory=lambda: Account.from_key(FIXTURE_KEY)
        )
    assert x402_wallet.KEY_ENV in str(exc.value)
    # The file is untouched: the refusal happens before any write.
    assert target.read_text() == f"{x402_wallet.KEY_ENV}=0xdead\n"


def test_write_env_force_appends_anyway(tmp_path):
    target = tmp_path / "env-file"
    target.write_text(f"{x402_wallet.KEY_ENV}=0xdead\n")
    args = x402_wallet.build_parser().parse_args(
        ["new", "--write-env", str(target), "--force"]
    )
    x402_wallet.cmd_new(
        args, out=Recorder(), account_factory=lambda: Account.from_key(FIXTURE_KEY)
    )
    assert target.read_text().count(f"{x402_wallet.KEY_ENV}=") == 2


def test_resolve_address_prefers_the_argument_then_env_then_the_key():
    assert x402_wallet.resolve_address(PAYEE, {}) == PAYEE
    assert x402_wallet.resolve_address(
        None, {x402_wallet.ADDRESS_ENV: PAYEE}
    ) == PAYEE
    # Derived from the key — the key itself never leaves the function.
    assert x402_wallet.resolve_address(
        None, {x402_wallet.KEY_ENV: FIXTURE_KEY}
    ) == FIXTURE_ADDRESS


def test_resolve_address_refuses_when_nothing_identifies_a_wallet():
    with pytest.raises(x402_wallet.WalletRefusal) as exc:
        x402_wallet.resolve_address(None, {})
    assert x402_wallet.ADDRESS_ENV in str(exc.value)


def test_balance_reports_both_balances_and_no_faucet_hint_when_funded():
    out = Recorder()
    args = x402_wallet.build_parser().parse_args(["balance", FIXTURE_ADDRESS])
    rc = x402_wallet.cmd_balance(args, out=out, w3=FakeW3(balance=20_000_000))
    assert rc == 0
    assert "20" in out.text
    assert "20000000 atomic" in out.text
    assert DEFAULT_USDC_ADDRESS in out.text
    assert x402_wallet.FAUCET_URL not in out.text


def test_balance_prints_the_faucet_instruction_at_zero():
    out = Recorder()
    args = x402_wallet.build_parser().parse_args(["balance", FIXTURE_ADDRESS])
    x402_wallet.cmd_balance(args, out=out, w3=FakeW3(balance=0))
    assert x402_wallet.FAUCET_URL in out.text
    assert "Base Sepolia" in out.text
    # The one thing an operator gets wrong: thinking they need gas.
    assert "No Base Sepolia ETH is needed" in out.text


def test_balance_warns_when_the_token_reports_unexpected_decimals():
    out = Recorder()
    args = x402_wallet.build_parser().parse_args(["balance", FIXTURE_ADDRESS])
    x402_wallet.cmd_balance(args, out=out, w3=FakeW3(balance=5, decimals=18))
    assert "WARNING" in out.text


def test_wallet_main_turns_a_refusal_into_exit_code_2(monkeypatch, capsys):
    monkeypatch.setattr(x402_wallet, "resolve_address", _raise_wallet_refusal)
    assert x402_wallet.main(["balance"]) == 2
    assert "refused:" in capsys.readouterr().err


def _raise_wallet_refusal(*args, **kwargs):
    raise x402_wallet.WalletRefusal("no address")


# ===========================================================================
# scripts/x402_e2e.py — parsing
# ===========================================================================

def test_e2e_parser_defaults_are_the_safe_ones():
    args = x402_e2e.build_parser().parse_args([])
    assert args.mode == "direct"
    assert args.dry_run is False
    assert args.max_usdc == "0.01"
    assert args.payee is None
    assert args.keep_db is False


def test_e2e_parser_rejects_an_unknown_mode():
    with pytest.raises(SystemExit):
        x402_e2e.build_parser().parse_args(["--mode", "mainnet"])


def test_e2e_parser_reads_the_pact_mode_flags():
    args = x402_e2e.build_parser().parse_args(
        ["--mode", "pact", "--dry-run", "--max-usdc", "0.02", "--payee", PAYEE]
    )
    assert args.mode == "pact" and args.dry_run is True
    assert args.max_usdc == "0.02" and args.payee == PAYEE


# ===========================================================================
# scripts/x402_e2e.py — refusals (each one fires BEFORE anything is signed)
# ===========================================================================

def test_resolve_payee_refuses_without_a_flag_or_env():
    with pytest.raises(x402_e2e.E2ERefusal) as exc:
        x402_e2e.resolve_payee(None, {})
    assert x402_e2e.PAYEE_ENV in str(exc.value)


def test_resolve_payee_reads_the_env_and_checksums_it():
    assert x402_e2e.resolve_payee(
        None, {x402_e2e.PAYEE_ENV: PAYEE.lower()}
    ) == PAYEE


def test_resolve_payee_prefers_the_flag():
    assert x402_e2e.resolve_payee(PAYEE, {x402_e2e.PAYEE_ENV: "0x" + "11" * 20}) == PAYEE


def test_resolve_payee_refuses_a_non_address():
    with pytest.raises(x402_e2e.E2ERefusal):
        x402_e2e.resolve_payee("not-an-address", {})


def test_max_usdc_atomic_converts_exactly():
    assert x402_e2e.max_usdc_atomic("0.01") == 10_000
    assert x402_e2e.max_usdc_atomic("1") == 1_000_000
    assert x402_e2e.max_usdc_atomic("0.000001") == 1


@pytest.mark.parametrize("value", ["abc", "-0.01", "nan", "0.0000001"])
def test_max_usdc_atomic_refuses_junk_and_sub_atomic_values(value):
    with pytest.raises(x402_e2e.E2ERefusal):
        x402_e2e.max_usdc_atomic(value)


def test_ensure_affordable_refuses_and_names_the_faucet():
    with pytest.raises(x402_e2e.E2ERefusal) as exc:
        x402_e2e.ensure_affordable(9_999, 10_000, FIXTURE_ADDRESS)
    assert "faucet.circle.com" in str(exc.value)
    # Exactly enough is enough.
    x402_e2e.ensure_affordable(10_000, 10_000, FIXTURE_ADDRESS)


def test_ensure_within_cap_refuses_a_quote_above_max_usdc():
    with pytest.raises(x402_e2e.E2ERefusal) as exc:
        x402_e2e.ensure_within_cap(20_000, 10_000)
    assert "nothing was signed" in str(exc.value)
    x402_e2e.ensure_within_cap(10_000, 10_000)


def test_e2e_setup_refuses_without_a_payer_key(monkeypatch):
    monkeypatch.setenv(x402_e2e.PAYEE_ENV, PAYEE)
    args = x402_e2e.build_parser().parse_args([])
    with pytest.raises(x402_e2e.E2ERefusal) as exc:
        x402_e2e.Setup(args)
    assert x402_e2e.KEY_ENV in str(exc.value)


def test_e2e_setup_resolves_the_payer_address_without_printing_the_key(monkeypatch, capsys):
    monkeypatch.setenv(x402_e2e.PAYEE_ENV, PAYEE)
    monkeypatch.setenv(x402_e2e.KEY_ENV, FIXTURE_KEY)
    setup = x402_e2e.Setup(x402_e2e.build_parser().parse_args([]))
    assert setup.payer == FIXTURE_ADDRESS
    assert setup.payee == PAYEE
    assert setup.price_atomic == 10_000
    assert setup.cap_atomic == 10_000
    setup.banner()
    printed = capsys.readouterr().out
    assert FIXTURE_ADDRESS in printed
    assert FIXTURE_KEY not in printed


def test_e2e_main_refuses_with_exit_code_2_when_no_payee(monkeypatch, capsys):
    monkeypatch.setenv(x402_e2e.KEY_ENV, FIXTURE_KEY)
    assert x402_e2e.main([]) == 2
    assert "refused:" in capsys.readouterr().err


# ===========================================================================
# scripts/x402_e2e.py — the seeding helper and the quote check
# ===========================================================================

class _AppShim:
    def __init__(self, db_path):
        self.config = {"DATABASE_PATH": db_path}


def test_seed_demo_asset_writes_the_one_row_the_gate_will_read(tmp_path):
    db_path = str(tmp_path / "e2e.db")
    init_db(_AppShim(db_path))
    asset_id = x402_e2e.seed_demo_asset(
        db_path, endpoint_url="http://127.0.0.1:9999", payee=PAYEE
    )
    row = get_skill_asset(db_path, asset_id)
    assert row["wallet_address"] == PAYEE
    assert row["endpoint_url"] == "http://127.0.0.1:9999"
    assert row["price_amount"] == 1
    assert row["price_currency"] == "USD"
    # One cent is 10_000 atomic USDC — the invariant the whole rail rests on.
    assert asset_price_atomic(row) == 10_000


def test_seeded_asset_is_resolvable_by_the_gate_helper(tmp_path):
    from app.services.x402_gate import resolve_asset_for_tool

    db_path = str(tmp_path / "e2e.db")
    init_db(_AppShim(db_path))
    endpoint = "http://127.0.0.1:9999"
    asset_id = x402_e2e.seed_demo_asset(db_path, endpoint_url=endpoint, payee=PAYEE)
    resolved = resolve_asset_for_tool(
        db_path, {x402_e2e.DEMO_TOOL: endpoint}, x402_e2e.DEMO_TOOL
    )
    assert resolved is not None and resolved["id"] == asset_id


def test_quote_problems_is_empty_for_the_quote_we_seeded():
    option = make_option(amount="10000", pay_to=PAYEE)
    assert x402_e2e.quote_problems(
        option, network=DEFAULT_NETWORK, asset=DEFAULT_USDC_ADDRESS,
        payee=PAYEE, price_atomic=10_000,
    ) == []


def test_quote_problems_names_a_redirected_payee():
    option = make_option(amount="10000", pay_to="0x" + "ab" * 20)
    problems = x402_e2e.quote_problems(
        option, network=DEFAULT_NETWORK, asset=DEFAULT_USDC_ADDRESS,
        payee=PAYEE, price_atomic=10_000,
    )
    assert len(problems) == 1 and "payTo" in problems[0]


def test_quote_problems_names_a_raised_price():
    option = make_option(amount="990000", pay_to=PAYEE)
    problems = x402_e2e.quote_problems(
        option, network=DEFAULT_NETWORK, asset=DEFAULT_USDC_ADDRESS,
        payee=PAYEE, price_atomic=10_000,
    )
    assert len(problems) == 1 and "amount" in problems[0]


def test_quote_problems_names_a_wrong_network_and_asset_together():
    option = make_option(
        amount="10000", pay_to=PAYEE, network="eip155:1",
        asset="0x" + "cd" * 20,
    )
    problems = x402_e2e.quote_problems(
        option, network=DEFAULT_NETWORK, asset=DEFAULT_USDC_ADDRESS,
        payee=PAYEE, price_atomic=10_000,
    )
    assert len(problems) == 2
    assert any("network" in p for p in problems)
    assert any("asset" in p for p in problems)


def test_payee_casing_never_makes_the_quote_look_wrong():
    option = make_option(amount="10000", pay_to=PAYEE.lower())
    assert x402_e2e.quote_problems(
        option, network=DEFAULT_NETWORK, asset=DEFAULT_USDC_ADDRESS,
        payee=PAYEE, price_atomic=10_000,
    ) == []


def test_usdc_formats_atomic_units_exactly():
    assert x402_e2e.usdc(10_000) == "0.01"
    assert x402_e2e.usdc("10000") == "0.01"
    assert x402_e2e.usdc(20_000_000) == "20"


def test_free_port_returns_a_usable_localhost_port():
    port = x402_e2e.free_port()
    assert isinstance(port, int) and 1024 < port < 65536
