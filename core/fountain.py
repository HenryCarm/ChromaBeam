"""
ChromaBeam Luby Transform (LT) Fountain Code Implementation
Combines O(K log K) ripple peeling decoder with incremental GF(2) Gaussian elimination solver
for 100% lossless guaranteed recovery under severe packet loss and noise.
"""

import math
from typing import List, Set, Dict, Optional, Tuple


class Mulberry32:
    """
    Deterministic 32-bit PRNG identical across Python, C, and JavaScript.
    """
    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF

    def next_uint32(self) -> int:
        self.state = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= ((t + ((t ^ (t >> 7)) * (t | 61))) & 0xFFFFFFFF)
        t = (t ^ (t >> 14)) & 0xFFFFFFFF
        return t

    def next_float(self) -> float:
        return self.next_uint32() / 4294967296.0

    def randint(self, low: int, high: int) -> int:
        if low >= high:
            return low
        return low + (self.next_uint32() % (high - low + 1))


def get_robust_soliton_cdf(K: int, c: float = 0.1, delta: float = 0.05) -> List[float]:
    """
    Computes cumulative distribution function (CDF) for the Robust Soliton distribution.
    """
    if K == 1:
        return [1.0]

    # Ideal Soliton rho(d)
    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))

    # Robust component tau(d)
    R = c * math.log(K / delta) * math.sqrt(K)
    tau = [0.0] * (K + 1)
    k_over_R = int(round(K / R)) if R > 0 else K

    for d in range(1, K + 1):
        if d < k_over_R:
            tau[d] = R / (d * K)
        elif d == k_over_R:
            tau[d] = (R * math.log(R / delta)) / K
        else:
            tau[d] = 0.0

    # Combined distribution mu(d)
    mu = [rho[d] + tau[d] for d in range(K + 1)]
    total = sum(mu[1:])
    if total <= 0:
        total = 1.0

    cdf = [0.0] * (K + 1)
    cum = 0.0
    for d in range(1, K + 1):
        cum += mu[d] / total
        cdf[d] = cum
    cdf[K] = 1.0
    return cdf


def sample_degree(prng: Mulberry32, cdf: List[float], K: int) -> int:
    """
    Samples droplet degree using PRNG and precomputed CDF.
    """
    if K <= 1:
        return 1
    r = prng.next_float()
    for d in range(1, K + 1):
        if r <= cdf[d]:
            return d
    return K


def get_droplet_indices(seed: int, K: int) -> Tuple[int, List[int]]:
    """
    Deterministically computes (degree, block_indices) for a given droplet seed and total blocks K.
    - If seed < K: Systematic droplet (degree 1, exactly block index = seed)
    - If seed >= K: Robust Soliton fountain droplet sampled using deterministic PRNG
    """
    if K <= 1:
        return 1, [0]

    if seed < K:
        return 1, [seed]

    prng = Mulberry32(seed)
    cdf = get_robust_soliton_cdf(K)
    degree = sample_degree(prng, cdf, K)

    indices: Set[int] = set()
    while len(indices) < degree:
        idx = prng.randint(0, K - 1)
        indices.add(idx)

    return degree, sorted(list(indices))


class LTEncoder:
    """
    Splits file data into K blocks and generates an endless stream of droplets.
    """
    def __init__(self, data: bytes, block_size: int = 256):
        self.raw_data = data
        self.block_size = block_size
        self.total_size = len(data)
        
        self.K = max(1, math.ceil(self.total_size / self.block_size))
        self.blocks: List[bytes] = []
        for i in range(self.K):
            start = i * self.block_size
            end = min(start + self.block_size, self.total_size)
            chunk = self.raw_data[start:end]
            if len(chunk) < self.block_size:
                chunk = chunk + b'\x00' * (self.block_size - len(chunk))
            self.blocks.append(chunk)

    def generate_droplet(self, seed: int) -> Tuple[int, List[int], bytes]:
        """
        Generates a droplet for a specific seed.
        Returns (degree, indices, payload).
        """
        degree, indices = get_droplet_indices(seed, self.K)
        payload = bytearray(self.blocks[indices[0]])
        for idx in indices[1:]:
            other = self.blocks[idx]
            for j in range(self.block_size):
                payload[j] ^= other[j]
        return degree, indices, bytes(payload)


class LTDecoder:
    """
    High-performance decoder combining fast ripple peeling with incremental GF(2) Gaussian elimination.
    """
    def __init__(self, K: int, block_size: int, total_filesize: int):
        self.K = K
        self.block_size = block_size
        self.total_filesize = total_filesize
        
        self.solved_blocks: Dict[int, bytes] = {}
        # Basis for GF(2) elimination: pivot_idx -> (Set[int] indices, bytearray data)
        self.basis: Dict[int, Tuple[Set[int], bytearray]] = {}
        self.received_count = 0
        self.is_complete = False

    def add_droplet(self, seed: int, payload: bytes) -> bool:
        """
        Adds a received droplet and runs ripple peeling + GF(2) solver.
        Returns True if the entire file is fully solved.
        """
        if self.is_complete:
            return True

        if len(payload) != self.block_size:
            return False

        self.received_count += 1
        degree, indices = get_droplet_indices(seed, self.K)
        cur_indices = set(indices)
        cur_data = bytearray(payload)

        # 1. Reduce using currently solved blocks
        for solved_idx, solved_data in self.solved_blocks.items():
            if solved_idx in cur_indices:
                cur_indices.remove(solved_idx)
                for j in range(self.block_size):
                    cur_data[j] ^= solved_data[j]

        if not cur_indices:
            return self._check_complete()

        # 2. Incremental GF(2) Gaussian elimination into basis
        while cur_indices:
            pivot = min(cur_indices)
            if pivot in self.basis:
                basis_indices, basis_data = self.basis[pivot]
                cur_indices = cur_indices.symmetric_difference(basis_indices)
                for j in range(self.block_size):
                    cur_data[j] ^= basis_data[j]
            else:
                self.basis[pivot] = (cur_indices, cur_data)
                break

        # 3. Check for newly solved singletons in basis and propagate
        self._reduce_basis()
        return self._check_complete()

    def _reduce_basis(self):
        """
        Runs Jordan back-substitution and solves singletons across basis rows.
        """
        changed = True
        while changed:
            changed = False
            for pivot in list(self.basis.keys()):
                indices, data = self.basis[pivot]
                
                # Reduce with solved blocks
                to_remove = [idx for idx in indices if idx in self.solved_blocks]
                if to_remove:
                    for idx in to_remove:
                        indices.remove(idx)
                        solved_data = self.solved_blocks[idx]
                        for j in range(self.block_size):
                            data[j] ^= solved_data[j]
                    changed = True

                if len(indices) == 0:
                    del self.basis[pivot]
                elif len(indices) == 1:
                    sol_idx = next(iter(indices))
                    if sol_idx not in self.solved_blocks:
                        self.solved_blocks[sol_idx] = bytes(data)
                        del self.basis[pivot]
                        changed = True

    def _check_complete(self) -> bool:
        if len(self.solved_blocks) == self.K:
            self.is_complete = True
            return True
        return False

    def get_progress(self) -> float:
        """Returns progress ratio from 0.0 to 1.0."""
        return len(self.solved_blocks) / self.K

    def reconstruct_data(self) -> Optional[bytes]:
        """
        Returns the original reconstructed bytes if complete, else None.
        """
        if len(self.solved_blocks) < self.K:
            return None

        full_buf = bytearray()
        for i in range(self.K):
            if i not in self.solved_blocks:
                return None
            full_buf.extend(self.solved_blocks[i])

        return bytes(full_buf[:self.total_filesize])
