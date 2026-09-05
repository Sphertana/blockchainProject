"""Arrange Besu's generated keys into per-validator folders and build the
static-nodes.json enode list with the fixed Docker IPs. Standard library only."""

import json
import shutil
from pathlib import Path

SRC = Path("network/networkFiles")
DST = Path("network/data")
IPS = ["172.28.0.11", "172.28.0.12", "172.28.0.13", "172.28.0.14"]


def main() -> None:
    nodes = sorted(p for p in (SRC / "keys").iterdir() if p.is_dir())
    assert len(nodes) == len(IPS), f"expected {len(IPS)} nodes, got {len(nodes)}"
    DST.mkdir(parents=True, exist_ok=True)
    shutil.copy(SRC / "genesis.json", DST / "genesis.json")

    enodes = []
    for i, node in enumerate(nodes):
        vdir = DST / f"validator{i + 1}"
        vdir.mkdir(parents=True, exist_ok=True)
        shutil.copy(node / "key", vdir / "key")
        pub = (node / "key.pub").read_text().strip()
        pub = pub[2:] if pub.startswith("0x") else pub
        enodes.append(f"enode://{pub}@{IPS[i]}:30303")

    (DST / "static-nodes.json").write_text(json.dumps(enodes, indent=2))
    print(f"laid out {len(nodes)} validators into {DST}")


if __name__ == "__main__":
    main()
