"""
Turn a REQUEST_HMAC_SECRET (from server/scripts/genkeys.mjs) into the
XOR-obfuscated byte array embedded in core/security.py.

Usage:
    python scripts/obfuscate_secret.py "Enoa8sXYTB7r/uPgqjh0lRA16p/yHe0zdmLaQlowk9w="

Paste the printed array over _OBSCURED_REQUEST_SECRET in core/security.py and
keep _REQUEST_SECRET_XOR_KEY in sync (default 0x5A).

Note: obfuscation only defeats a plain `strings` dump. A skilled reverser can
still recover the secret - it is not the primary trust anchor (the Ed25519
public key is).
"""

import sys

XOR_KEY = 0x5A


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    secret = sys.argv[1]
    obf = [ord(c) ^ XOR_KEY for c in secret]
    assert "".join(chr(b ^ XOR_KEY) for b in obf) == secret

    lines = []
    for i in range(0, len(obf), 16):
        lines.append("    " + ", ".join(f"0x{b:02x}" for b in obf[i:i + 16]) + ",")
    print(f"_REQUEST_SECRET_XOR_KEY = 0x{XOR_KEY:02X}\n")
    print("_OBSCURED_REQUEST_SECRET = bytes([")
    print("\n".join(lines))
    print("])")


if __name__ == "__main__":
    main()
