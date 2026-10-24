"""Merkle tree matching the SQL function merkle_root() exactly.

leaf  = sha256('L' + row_hash_hex)            (hex text in, hex text out)
node  = sha256('N' + left_hex + right_hex)
A node with no sibling is promoted unchanged.
"""
import hashlib


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def leaf(row_hash: str) -> str:
    return _h("L" + row_hash)


def node(left: str, right: str) -> str:
    return _h("N" + left + right)


def levels(row_hashes):
    lvl = [leaf(x) for x in row_hashes]
    out = [lvl]
    while len(lvl) > 1:
        nxt = []
        for i in range(0, len(lvl), 2):
            nxt.append(node(lvl[i], lvl[i + 1]) if i + 1 < len(lvl) else lvl[i])
        lvl = nxt
        out.append(lvl)
    return out


def root(row_hashes):
    if not row_hashes:
        raise ValueError("no leaves")
    return levels(row_hashes)[-1][0]


def proof(row_hashes, index):
    """Inclusion proof for leaf `index`: list of (side, sibling_hex); side is where the sibling sits."""
    path = []
    idx = index
    for lvl in levels(row_hashes)[:-1]:
        sib = idx ^ 1
        if sib < len(lvl):
            path.append(("R" if sib > idx else "L", lvl[sib]))
        idx //= 2
    return path


def verify(row_hash, path, expected_root):
    cur = leaf(row_hash)
    for side, sib in path:
        cur = node(cur, sib) if side == "R" else node(sib, cur)
    return cur == expected_root
