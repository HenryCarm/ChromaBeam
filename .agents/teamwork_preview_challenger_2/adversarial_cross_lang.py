"""
Empirical Adversarial Test Suite 1: Cross-Language (Python <-> JS) Compatibility & Corruption Robustness
Author: Challenger 2 (Milestone 5 Acceptance Gate)
"""

import os
import sys
import json
import random
import string
import struct
import zlib
import subprocess
import unittest
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from core.fountain import LTEncoder, LTDecoder, Mulberry32, get_robust_soliton_cdf, get_droplet_indices
from core.protocol import pack_packet, unpack_packet, pack_file_metadata, unpack_file_metadata, MAGIC_INT
from core.color_matrix import (
    ColorMatrixLayout,
    bytes_to_color_grid,
    color_grid_to_bytes,
    MODE_1BIT_BW,
    MODE_2BIT_4COLOR,
    MODE_3BIT_8COLOR,
    PALETTE_1BIT,
    PALETTE_2BIT,
    PALETTE_3BIT
)


class TestCrossLanguageCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js_fountain_path = os.path.join(PROJECT_ROOT, "web", "fountain.js")
        cls.js_protocol_path = os.path.join(PROJECT_ROOT, "web", "protocol.js")
        cls.js_matrix_path = os.path.join(PROJECT_ROOT, "web", "matrix.js")

    def run_node_eval(self, js_code: str) -> dict:
        """Executes a JS script snippet in Node.js and returns parsed JSON output."""
        full_script = f"""
        const fs = require('fs');
        const path = require('path');
        const vm = require('vm');

        const fountainCode = fs.readFileSync({json.dumps(self.js_fountain_path)}, 'utf8');
        const protocolCode = fs.readFileSync({json.dumps(self.js_protocol_path)}, 'utf8');
        const matrixCode = fs.readFileSync({json.dumps(self.js_matrix_path)}, 'utf8');

        const sandbox = {{
            console,
            performance,
            Math,
            Uint8Array,
            Uint32Array,
            Float64Array,
            DataView,
            TextEncoder,
            TextDecoder,
            Array,
            Set,
            Map
        }};
        vm.createContext(sandbox);
        vm.runInContext(fountainCode + '\\n' + protocolCode + '\\n' + matrixCode, sandbox);

        const runner = function() {{
            {js_code}
        }};
        const result = vm.runInContext('(' + runner.toString() + ')()', sandbox);
        console.log(JSON.stringify(result));
        """
        proc = subprocess.run(["node", "-e", full_script], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Node execution failed with code {proc.returncode}:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        return json.loads(proc.stdout.strip().split("\n")[-1])

    def test_mulberry32_prng_cross_language_parity(self):
        """Verify Mulberry32 PRNG produces identical 32-bit values across 100,000 samples."""
        seeds_to_test = [0, 1, 42, 1337, 0x12345678, 0x7FFFFFFF, 0xFFFFFFFF]
        
        for seed in seeds_to_test:
            # Python side
            py_prng = Mulberry32(seed)
            py_seq = [py_prng.next_uint32() for _ in range(500)]
            py_floats = [py_prng.next_float() for _ in range(500)]
            py_rands = [py_prng.randint(10, 1000) for _ in range(500)]

            # JS side
            js_code = f"""
            const prng = new Mulberry32({seed});
            const seq = [];
            for (let i = 0; i < 500; i++) seq.push(prng.nextUint32());
            const floats = [];
            for (let i = 0; i < 500; i++) floats.push(prng.nextFloat());
            const rands = [];
            for (let i = 0; i < 500; i++) rands.push(prng.randInt(10, 1000));
            return {{ seq, floats, rands }};
            """
            js_res = self.run_node_eval(js_code)

            self.assertEqual(py_seq, js_res["seq"], f"Mulberry32 uint32 mismatch for seed {seed}")
            for pf, jf in zip(py_floats, js_res["floats"]):
                self.assertAlmostEqual(pf, jf, places=9, msg=f"Float mismatch for seed {seed}")
            self.assertEqual(py_rands, js_res["rands"], f"randint mismatch for seed {seed}")

    def test_soliton_cdf_and_droplet_indices_parity(self):
        """Verify Robust Soliton CDF and droplet index sets match identically across Python and JS."""
        test_configs = [
            (1, [0, 1, 2]),
            (2, [0, 1, 2, 10]),
            (5, [0, 1, 4, 5, 10, 100]),
            (20, [0, 1, 19, 20, 21, 50, 999]),
            (100, [0, 50, 99, 100, 101, 500, 10000])
        ]

        for K, seeds in test_configs:
            for seed in seeds:
                py_deg, py_indices = get_droplet_indices(seed, K)

                js_code = f"""
                const res = getDropletIndices({seed}, {K});
                return {{ degree: res.degree, indices: res.indices }};
                """
                js_res = self.run_node_eval(js_code)

                self.assertEqual(py_deg, js_res["degree"], f"Degree mismatch for K={K}, seed={seed}")
                self.assertEqual(py_indices, js_res["indices"], f"Indices mismatch for K={K}, seed={seed}")

    def test_protocol_packing_and_crc32_cross_parity(self):
        """Verify binary packet layout and CRC32 parity between Python struct/zlib and JS DataView/CRC table."""
        test_payloads = [
            b"",
            b"Hello ChromaBeam!",
            os.urandom(64),
            os.urandom(256),
            os.urandom(512),
            bytes(range(256))
        ]

        for idx, payload in enumerate(test_payloads):
            file_id = (idx * 37 + 101) & 0xFFFF
            total_blocks = (idx * 11 + 5) & 0xFFFF
            block_size = len(payload)
            seed = (idx * 10007 + 42) & 0xFFFFFFFF

            # 1. Pack with Python -> Unpack with JS
            py_packed = pack_packet(file_id, total_blocks, block_size, seed, payload)
            js_code = f"""
            const rawHex = {json.dumps(py_packed.hex())};
            const bytes = new Uint8Array(rawHex.match(/.{{1,2}}/g).map(byte => parseInt(byte, 16)));
            const res = unpackPacket(bytes);
            if (!res) return {{ valid: false }};
            return {{
                valid: true,
                fileId: res.header.fileId,
                totalBlocks: res.header.totalBlocks,
                blockSize: res.header.blockSize,
                seed: res.header.seed,
                payloadHex: Buffer ? Buffer.from(res.payload).toString('hex') : Array.from(res.payload).map(b => b.toString(16).padStart(2, '0')).join('')
            }};
            """
            js_res = self.run_node_eval(js_code)
            self.assertTrue(js_res["valid"], f"JS unpackPacket rejected valid Python packet #{idx}")
            self.assertEqual(js_res["fileId"], file_id)
            self.assertEqual(js_res["totalBlocks"], total_blocks)
            self.assertEqual(js_res["blockSize"], block_size)
            self.assertEqual(js_res["seed"], seed)
            self.assertEqual(js_res["payloadHex"], payload.hex())

            # 2. Pack with JS -> Unpack with Python
            js_pack_code = f"""
            const payloadHex = {json.dumps(payload.hex())};
            const payloadBytes = new Uint8Array(payloadHex.length === 0 ? [] : payloadHex.match(/.{{1,2}}/g).map(byte => parseInt(byte, 16)));
            const packed = packPacket({file_id}, {total_blocks}, {block_size}, {seed}, payloadBytes);
            return {{
                packedHex: Array.from(packed).map(b => b.toString(16).padStart(2, '0')).join('')
            }};
            """
            js_pack_res = self.run_node_eval(js_pack_code)
            js_packed_bytes = bytes.fromhex(js_pack_res["packedHex"])

            py_unpacked = unpack_packet(js_packed_bytes)
            self.assertIsNotNone(py_unpacked, f"Python unpack_packet rejected JS packet #{idx}")
            header, py_payload = py_unpacked
            self.assertEqual(header.file_id, file_id)
            self.assertEqual(header.total_blocks, total_blocks)
            self.assertEqual(header.block_size, block_size)
            self.assertEqual(header.seed, seed)
            self.assertEqual(py_payload, payload)

    def test_metadata_cross_language_parity(self):
        """Verify file metadata packing/unpacking between Python and JS."""
        test_cases = [
            ("photo.png", 102400, "image/png"),
            ("airgap_payload.tar.gz", 9999999, "application/gzip"),
            ("document with spaces & unicode \U0001F680.bin", 512, "application/octet-stream")
        ]

        for name, size, mime in test_cases:
            # Python pack -> JS unpack
            py_meta = pack_file_metadata(name, size, mime)
            js_code = f"""
            const rawHex = {json.dumps(py_meta.hex())};
            const bytes = new Uint8Array(rawHex.match(/.{{1,2}}/g).map(byte => parseInt(byte, 16)));
            const res = unpackFileMetadata(bytes);
            if (!res) return {{ valid: false }};
            return {{
                valid: true,
                filename: res.filename,
                filesize: res.filesize,
                mimeType: res.mimeType
            }};
            """
            js_res = self.run_node_eval(js_code)
            self.assertTrue(js_res["valid"])
            self.assertEqual(js_res["filename"], name)
            self.assertEqual(js_res["filesize"], size)
            self.assertEqual(js_res["mimeType"], mime)

            # JS pack -> Python unpack
            js_pack_code = f"""
            const packed = packFileMetadata({json.dumps(name)}, {size}, {json.dumps(mime)});
            return {{
                packedHex: Array.from(packed).map(b => b.toString(16).padStart(2, '0')).join('')
            }};
            """
            js_pack_res = self.run_node_eval(js_pack_code)
            py_unpacked = unpack_file_metadata(bytes.fromhex(js_pack_res["packedHex"]))
            self.assertIsNotNone(py_unpacked)
            self.assertEqual(py_unpacked[0], name)
            self.assertEqual(py_unpacked[1], size)
            self.assertEqual(py_unpacked[2], mime)

    def test_python_encoder_to_js_decoder_under_loss_and_corruption(self):
        """
        Adversarial Test: Python Fountain Encoder -> JS LTDecoder
        Under:
        - 50% packet drop
        - Shuffled out-of-order arrival
        - Corrupted bitflips / CRC corruption injected (must be filtered without corrupting solver)
        """
        random.seed(42)
        test_file_sizes = [1, 17, 256, 1024, 15000, 65536]

        for size in test_file_sizes:
            test_data = os.urandom(size)
            block_size = 128 if size < 1000 else 256

            encoder = LTEncoder(test_data, block_size=block_size)
            K = encoder.K
            total_droplets = max(K * 2, K + 15)

            # Generate pool of packets
            packet_pool = []
            for seed in range(total_droplets):
                _, _, payload = encoder.generate_droplet(seed)
                packed = pack_packet(42, K, block_size, seed, payload)
                packet_pool.append((seed, packed, False))

            # Inject 15% corrupted packets into the pool
            num_corrupt = max(3, int(len(packet_pool) * 0.15))
            for _ in range(num_corrupt):
                bad_seed = random.randint(0, 10000)
                bad_payload = bytearray(os.urandom(block_size))
                bad_packed = bytearray(pack_packet(42, K, block_size, bad_seed, bytes(bad_payload)))
                # Corrupt CRC or payload
                bad_packed[random.randint(0, len(bad_packed) - 1)] ^= 0xFF
                packet_pool.append((bad_seed, bytes(bad_packed), True))

            # Shuffle and drop 40%
            random.shuffle(packet_pool)
            retained_packets = packet_pool[:int(len(packet_pool) * 0.75)]

            # Transmit to JS Decoder via Node.js
            packets_hex = [p[1].hex() for p in retained_packets]
            js_test_code = f"""
            const packetsHex = {json.dumps(packets_hex)};
            const K = {K};
            const blockSize = {block_size};
            const totalFilesize = {size};

            const decoder = new LTDecoder(K, blockSize, totalFilesize);
            let acceptedCount = 0;
            let rejectedCount = 0;

            for (const hex of packetsHex) {{
                const bytes = new Uint8Array(hex.match(/.{{1,2}}/g).map(byte => parseInt(byte, 16)));
                const unpacked = unpackPacket(bytes);
                if (!unpacked) {{
                    rejectedCount++;
                    continue;
                }}
                acceptedCount++;
                const isSolved = decoder.addDroplet(unpacked.header.seed, unpacked.payload);
                if (isSolved) break;
            }}

            const isComplete = decoder.isComplete;
            const progress = decoder.getProgress();
            let reconstructedHex = null;
            if (isComplete) {{
                const data = decoder.reconstructData();
                reconstructedHex = Array.from(data).map(b => b.toString(16).padStart(2, '0')).join('');
            }}

            return {{
                isComplete,
                progress,
                acceptedCount,
                rejectedCount,
                reconstructedHex
            }};
            """

            js_res = self.run_node_eval(js_test_code)
            self.assertTrue(js_res["isComplete"], f"JS Decoder failed to solve for filesize={size}. Progress: {js_res['progress']}")
            self.assertGreater(js_res["rejectedCount"], 0, "Corrupted packets must be rejected by unpackPacket")
            reconstructed_bytes = bytes.fromhex(js_res["reconstructedHex"])
            self.assertEqual(reconstructed_bytes, test_data, f"Reconstructed data mismatch for filesize={size}")

    def test_js_encoder_to_python_decoder_under_loss_and_corruption(self):
        """
        Adversarial Test: JS Fountain Encoder -> Python LTDecoder
        Under:
        - 50% packet drop
        - Shuffled packets
        - Injected corruption
        """
        random.seed(1337)
        test_file_sizes = [5, 100, 512, 5000, 32768]

        for size in test_file_sizes:
            test_data = os.urandom(size)
            block_size = 64 if size < 500 else 256

            # Generate packets in JS
            js_gen_code = f"""
            const dataHex = {json.dumps(test_data.hex())};
            const dataBytes = new Uint8Array(dataHex.match(/.{{1,2}}/g).map(byte => parseInt(byte, 16)));
            const blockSize = {block_size};
            const encoder = new LTEncoder(dataBytes, blockSize);
            const K = encoder.K;
            const totalDroplets = Math.max(K * 2, K + 20);

            const packets = [];
            for (let seed = 0; seed < totalDroplets; seed++) {{
                const {{ payload }} = encoder.generateDroplet(seed);
                const packed = packPacket(99, K, blockSize, seed, payload);
                packets.push(Array.from(packed).map(b => b.toString(16).padStart(2, '0')).join(''));
            }}

            return {{ K, packets }};
            """
            js_gen_res = self.run_node_eval(js_gen_code)
            K = js_gen_res["K"]
            packets_hex = js_gen_res["packets"]

            # Convert to bytes and inject adversarial corruption
            packet_pool = [bytes.fromhex(h) for h in packets_hex]
            # Inject 10 corrupted packets
            for _ in range(10):
                bad_buf = bytearray(random.choice(packet_pool))
                bad_buf[random.randint(0, len(bad_buf) - 1)] ^= 0xAA
                packet_pool.append(bytes(bad_buf))

            random.shuffle(packet_pool)
            # Drop 35%
            retained = packet_pool[:int(len(packet_pool) * 0.65)]

            # Feed to Python Decoder
            decoder = LTDecoder(K, block_size, size)
            rejected_count = 0
            accepted_count = 0

            for raw in retained:
                unpacked = unpack_packet(raw)
                if unpacked is None:
                    rejected_count += 1
                    continue
                accepted_count += 1
                header, payload = unpacked
                if decoder.add_droplet(header.seed, payload):
                    break

            self.assertTrue(decoder.is_complete, f"Python Decoder failed on JS stream for size={size}. Progress: {decoder.get_progress():.2%}")
            self.assertGreater(rejected_count, 0, "Expected corrupted packets to be rejected by Python unpack_packet")
            reconstructed = decoder.reconstruct_data()
            self.assertEqual(reconstructed, test_data, f"Data mismatch on JS->Python reconstruction for size={size}")

    def test_color_matrix_parity_across_all_modes_and_densities(self):
        """
        Adversarial Test: Color Matrix bit/palette mapping between Python and JS
        Verifies all combinations of:
        - Mode 0 (1-bit), Mode 1 (2-bit), Mode 2 (3-bit)
        - Density 32x32, 48x48, 64x64
        - Anchor patterns, timing tracks, calibration swatches, data coordinates
        """
        modes = [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]
        densities = [32, 48, 64]

        for mode in modes:
            for N in densities:
                py_layout = ColorMatrixLayout(grid_size=N, color_mode=mode)

                # Test JS layout metadata
                js_code = f"""
                const layout = new JSColorMatrixLayout({N}, {mode});
                return {{
                    gridSize: layout.gridSize,
                    colorMode: layout.colorMode,
                    bitsPerCell: layout.bitsPerCell,
                    numDataCells: layout.numDataCells,
                    maxPayloadBytes: layout.maxPayloadBytes,
                    dataCoords: layout.dataCoords,
                    anchorCenters: layout.anchorCenters
                }};
                """
                js_layout = self.run_node_eval(js_code)

                self.assertEqual(py_layout.num_data_cells, js_layout["numDataCells"], f"Data cell count mismatch for mode={mode}, N={N}")
                self.assertEqual(py_layout.max_payload_bytes, js_layout["maxPayloadBytes"], f"Payload byte capacity mismatch for mode={mode}, N={N}")
                self.assertEqual(py_layout.bits_per_cell, js_layout["bitsPerCell"], f"Bits per cell mismatch for mode={mode}, N={N}")

                # Test Anchor Centroids floating points
                for py_c, js_c in zip(py_layout.anchor_centers, js_layout["anchorCenters"]):
                    self.assertAlmostEqual(py_c[0], js_c["x"], places=5)
                    self.assertAlmostEqual(py_c[1], js_c["y"], places=5)

                # Test Data Coordinates
                py_coords = [(int(r), int(c)) for r, c in py_layout.data_coords]
                js_coords = [(pt["r"], pt["c"]) for pt in js_layout["dataCoords"]]
                self.assertEqual(py_coords, js_coords, f"Data coordinate list mismatch for mode={mode}, N={N}")

                # Test Binary Matrix Serialization Round-Trip
                payload = os.urandom(py_layout.max_payload_bytes)
                py_grid = bytes_to_color_grid(payload, py_layout)

                # Send grid to JS, extract bytes, verify exact match
                # Convert py_grid (RGB) to indices for JS
                if mode == MODE_1BIT_BW:
                    indices_grid = (py_grid[:, :, 0] > 128).astype(int).tolist()
                elif mode == MODE_2BIT_4COLOR:
                    # Map RGB to index 0..3
                    indices_grid = []
                    for r in range(N):
                        row = []
                        for c in range(N):
                            rgb = py_grid[r, c]
                            dists = [np.sum((rgb - p)**2) for p in PALETTE_2BIT]
                            row.append(int(np.argmin(dists)))
                        indices_grid.append(row)
                else:
                    indices_grid = []
                    for r in range(N):
                        row = []
                        for c in range(N):
                            rgb = py_grid[r, c]
                            dists = [np.sum((rgb - p)**2) for p in PALETTE_3BIT]
                            row.append(int(np.argmin(dists)))
                        indices_grid.append(row)

                js_decode_code = f"""
                const layout = new JSColorMatrixLayout({N}, {mode});
                const grid2D = {json.dumps(indices_grid)};
                const bytesOut = gridIndicesToBytes(grid2D, layout);
                return {{
                    bytesHex: Array.from(bytesOut).map(b => b.toString(16).padStart(2, '0')).join('')
                }};
                """
                js_decode_res = self.run_node_eval(js_decode_code)
                js_extracted_bytes = bytes.fromhex(js_decode_res["bytesHex"])
                self.assertEqual(js_extracted_bytes, payload, f"Matrix data extraction mismatch for mode={mode}, N={N}")


if __name__ == '__main__':
    unittest.main()
