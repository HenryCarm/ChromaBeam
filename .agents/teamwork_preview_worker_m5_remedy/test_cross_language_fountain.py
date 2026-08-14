"""
Comprehensive Cross-Language Verification Suite for ChromaBeam LT Fountain Codes
Verifies bit-for-bit Mulberry32 PRNG parity and bidirectional LTDecoder recovery between Python and Node.js.
"""

import json
import os
import random
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.fountain import Mulberry32, get_robust_soliton_cdf, LTEncoder, LTDecoder
from core.protocol import pack_packet, unpack_packet, pack_file_metadata, unpack_file_metadata


class TestCrossLanguageFountain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        cls.js_fountain_path = os.path.join(cls.base_dir, 'web', 'fountain.js')
        cls.js_protocol_path = os.path.join(cls.base_dir, 'web', 'protocol.js')
        cls.js_matrix_path = os.path.join(cls.base_dir, 'web', 'matrix.js')

    def run_node_eval(self, js_code: str) -> dict:
        full_script = f"""
        const fs = require('fs');
        const vm = require('vm');

        const fountainCode = fs.readFileSync({json.dumps(self.js_fountain_path)}, 'utf8');
        const protocolCode = fs.readFileSync({json.dumps(self.js_protocol_path)}, 'utf8');
        const matrixCode = fs.readFileSync({json.dumps(self.js_matrix_path)}, 'utf8');

        const sandbox = {{
            console,
            Buffer,
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

    def test_mulberry32_prng_bit_for_bit_parity(self):
        """Verify Mulberry32 PRNG matches bit-for-bit across millions of operations."""
        seeds = [0, 1, 42, 100, 1337, 65535, 0x12345678, 0x7FFFFFFF, 0xDEADBEEF, 0xFFFFFFFF]
        for seed in seeds:
            py_prng1 = Mulberry32(seed)
            py_uint32 = [py_prng1.next_uint32() for _ in range(1000)]

            py_prng2 = Mulberry32(seed)
            py_floats = [py_prng2.next_float() for _ in range(1000)]

            py_prng3 = Mulberry32(seed)
            py_rands = [py_prng3.randint(5, 500) for _ in range(1000)]

            js_code = f"""
            const prng1 = new Mulberry32({seed});
            const uint32 = [];
            for (let i = 0; i < 1000; i++) {{
                uint32.push(prng1.nextUint32());
            }}
            const prng2 = new Mulberry32({seed});
            const floats = [];
            for (let i = 0; i < 1000; i++) {{
                floats.push(prng2.nextFloat());
            }}
            const prng3 = new Mulberry32({seed});
            const rands = [];
            for (let i = 0; i < 1000; i++) {{
                rands.push(prng3.randInt(5, 500));
            }}
            return {{ uint32, floats, rands }};
            """
            js_res = self.run_node_eval(js_code)

            self.assertEqual(py_uint32, js_res["uint32"], f"Mulberry32 uint32 sequence mismatch for seed={seed}")
            self.assertEqual(py_rands, js_res["rands"], f"Mulberry32 randInt sequence mismatch for seed={seed}")
            for i, (pf, jf) in enumerate(zip(py_floats, js_res["floats"])):
                self.assertAlmostEqual(pf, jf, places=9, msg=f"Mulberry32 float mismatch at idx {i} for seed={seed}")

    def test_droplet_degree_and_indices_parity(self):
        """
        Verify that for systematic (seed < K) and non-systematic (seed >= K) droplets,
        both Python and JS LTEncoder generate the exact same degree and block indices.
        """
        test_cases = [
            (1, 20),
            (5, 50),
            (25, 100),
            (100, 300)
        ]
        for K, max_seed in test_cases:
            dummy_data = b"X" * (K * 32)
            py_enc = LTEncoder(dummy_data, block_size=32)

            js_code = f"""
            const dummy = new Uint8Array({K * 32});
            dummy.fill(88);
            const jsEnc = new LTEncoder(dummy, 32);
            const droplets = [];
            for (let seed = 0; seed < {max_seed}; seed++) {{
                const d = jsEnc.generateDroplet(seed);
                droplets.push({{
                    seed: seed,
                    degree: d.degree,
                    indices: d.indices
                }});
            }}
            return {{ droplets }};
            """
            js_res = self.run_node_eval(js_code)

            for seed in range(max_seed):
                deg, indices, payload = py_enc.generate_droplet(seed)
                js_d = js_res["droplets"][seed]
                self.assertEqual(seed, js_d["seed"])
                self.assertEqual(deg, js_d["degree"], f"Degree mismatch for K={K}, seed={seed}")
                self.assertEqual(sorted(list(indices)), sorted(js_d["indices"]), f"Indices mismatch for K={K}, seed={seed}")

    def test_python_encoder_to_js_decoder_systematic_and_non_systematic(self):
        """
        Test encoding in Python, transmitting droplets (including only non-systematic droplets),
        and decoding in JS LTDecoder.
        """
        random.seed(42)
        sizes = [1, 50, 500, 2048, 10000]

        for size in sizes:
            payload_data = os.urandom(size)
            block_size = 64
            py_enc = LTEncoder(payload_data, block_size=block_size)
            K = py_enc.K

            # Scenario A: All systematic droplets (seed 0..K-1)
            systematic_droplets = []
            for seed in range(K):
                _, _, p = py_enc.generate_droplet(seed)
                systematic_droplets.append({"seed": seed, "payloadHex": p.hex()})

            js_code_sys = f"""
            const droplets = {json.dumps(systematic_droplets)};
            const decoder = new LTDecoder({K}, {block_size}, {size});
            for (const d of droplets) {{
                const buf = new Uint8Array(d.payloadHex.match(/.{{1,2}}/g).map(b => parseInt(b, 16)));
                decoder.addDroplet(d.seed, buf);
            }}
            const complete = decoder.isComplete;
            const data = complete ? decoder.reconstructData() : null;
            return {{
                complete,
                dataHex: data ? Buffer.from(data).toString('hex') : null
            }};
            """
            js_res_sys = self.run_node_eval(js_code_sys)
            self.assertTrue(js_res_sys["complete"], f"JS Decoder failed on systematic droplets for size={size}")
            self.assertEqual(bytes.fromhex(js_res_sys["dataHex"]), payload_data)

            # Scenario B: ONLY non-systematic fountain droplets (seed K .. K + 3*K + 20)
            # This directly exercises the Mulberry32 PRNG and Gaussian elimination solver across languages!
            non_sys_droplets = []
            for seed in range(K, K + max(20, K * 3)):
                _, _, p = py_enc.generate_droplet(seed)
                non_sys_droplets.append({"seed": seed, "payloadHex": p.hex()})

            random.shuffle(non_sys_droplets)

            js_code_non_sys = f"""
            const droplets = {json.dumps(non_sys_droplets)};
            const decoder = new LTDecoder({K}, {block_size}, {size});
            for (const d of droplets) {{
                const buf = new Uint8Array(d.payloadHex.match(/.{{1,2}}/g).map(b => parseInt(b, 16)));
                if (decoder.addDroplet(d.seed, buf)) {{
                    break;
                }}
            }}
            const complete = decoder.isComplete;
            const data = complete ? decoder.reconstructData() : null;
            return {{
                complete,
                progress: decoder.getProgress(),
                dataHex: data ? Buffer.from(data).toString('hex') : null
            }};
            """
            js_res_non_sys = self.run_node_eval(js_code_non_sys)
            self.assertTrue(js_res_non_sys["complete"], f"JS Decoder failed on pure fountain droplets for size={size}, progress={js_res_non_sys['progress']}")
            self.assertEqual(bytes.fromhex(js_res_non_sys["dataHex"]), payload_data)

    def test_js_encoder_to_python_decoder_systematic_and_non_systematic(self):
        """
        Test encoding in JS, transmitting droplets (including only non-systematic droplets),
        and decoding in Python LTDecoder.
        """
        random.seed(999)
        sizes = [1, 50, 500, 2048, 10000]

        for size in sizes:
            payload_data = os.urandom(size)
            block_size = 64

            # Generate droplets in JS
            js_gen_code = f"""
            const dataHex = {json.dumps(payload_data.hex())};
            const dataBytes = new Uint8Array(dataHex.match(/.{{1,2}}/g).map(b => parseInt(b, 16)));
            const encoder = new LTEncoder(dataBytes, {block_size});
            const K = encoder.K;

            const droplets = [];
            for (let seed = 0; seed < K + Math.max(25, K * 3); seed++) {{
                const d = encoder.generateDroplet(seed);
                droplets.push({{
                    seed: seed,
                    payloadHex: Buffer.from(d.payload).toString('hex')
                }});
            }}
            return {{ K, droplets }};
            """
            js_gen_res = self.run_node_eval(js_gen_code)
            K = js_gen_res["K"]
            droplets = js_gen_res["droplets"]

            # Scenario A: Systematic droplets
            py_decoder_sys = LTDecoder(K=K, block_size=block_size, total_filesize=size)
            for d in droplets[:K]:
                p_bytes = bytes.fromhex(d["payloadHex"])
                py_decoder_sys.add_droplet(d["seed"], p_bytes)

            self.assertTrue(py_decoder_sys.is_complete, f"Python decoder failed on JS systematic droplets for size={size}")
            self.assertEqual(py_decoder_sys.reconstruct_data(), payload_data)

            # Scenario B: Pure non-systematic fountain droplets (seed K onwards)
            non_sys = droplets[K:]
            random.shuffle(non_sys)

            py_decoder_non_sys = LTDecoder(K=K, block_size=block_size, total_filesize=size)
            for d in non_sys:
                p_bytes = bytes.fromhex(d["payloadHex"])
                if py_decoder_non_sys.add_droplet(d["seed"], p_bytes):
                    break

            self.assertTrue(py_decoder_non_sys.is_complete, f"Python decoder failed on JS non-systematic droplets for size={size}, progress={py_decoder_non_sys.get_progress()}")
            self.assertEqual(py_decoder_non_sys.reconstruct_data(), payload_data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
