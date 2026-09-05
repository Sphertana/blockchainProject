"""Compile ClassLedger.sol into a committed ABI+bytecode artifact.

Run this only when the contract changes (`make compile`); the app and tests
load the produced JSON so runtime needs no Solidity compiler.
"""

import json
from pathlib import Path

import solcx
from solcx.exceptions import SolcNotInstalled

SRC = Path("contracts/ClassLedger.sol")
OUT = Path("contracts/artifacts/ClassLedger.json")
SOLC_VERSION = "0.8.24"


def main() -> None:
    # Use an already-installed solc if present; only reach the network otherwise.
    try:
        solcx.set_solc_version(SOLC_VERSION)
    except SolcNotInstalled:
        solcx.install_solc(SOLC_VERSION)
    compiled = solcx.compile_files(
        [str(SRC)],
        output_values=["abi", "bin"],
        solc_version=SOLC_VERSION,
        evm_version="berlin",  # match the Besu chain; avoids PUSH0 (Shanghai)
        optimize=True,
    )
    art = compiled[f"{SRC}:ClassLedger"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"abi": art["abi"], "bytecode": art["bin"]}, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
