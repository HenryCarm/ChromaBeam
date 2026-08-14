# ChromaBeam Milestone 5 Final Acceptance Gate — Challenger 2 Report

## Verdict
**`REQUEST_CHANGES`**

---

## 1. Observation

During adversarial stress-testing of cross-language compatibility (Python vs JS), offline Web Worker bundle integrity, and auto-density sweeping under rapid mode switching, empirical testing identified three distinct failure modes:

### Observation 1.1: JavaScript Mulberry32 PRNG Typo Breaking Non-Systematic Fountain Parity
- **File**: `/home/henry/Documents/Projects/Python/QR ChromaBeam/web/fountain.js`, Line 15
- **Current JS Code**:
  ```javascript
  14: t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
  15: t ^= (t + Math.imul(t ^ (t >>> 7), 61)) >>> 0;
  16: return (t ^ (t >>> 14)) >>> 0;
  ```
- **Corresponding Python Code** (`/home/henry/Documents/Projects/Python/QR ChromaBeam/core/fountain.py`, Line 22):
  ```python
  21: t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
  22: t ^= ((t + ((t ^ (t >> 7)) * (t | 61))) & 0xFFFFFFFF)
  23: t = (t ^ (t >> 14)) & 0xFFFFFFFF
  ```
- **Verbatim Error in Test Run** (`adversarial_cross_lang.py`):
  ```
  FAIL: test_mulberry32_prng_cross_language_parity (__main__.TestCrossLanguageCompatibility)
  AssertionError: Lists differ: [1144304738, 1416247, ...] != [510550180, 816623568, ...] : Mulberry32 uint32 mismatch for seed 0

  FAIL: test_soliton_cdf_and_droplet_indices_parity (__main__.TestCrossLanguageCompatibility)
  AssertionError: 2 != 1 : Degree mismatch for K=2, seed=2

  FAIL: test_js_encoder_to_python_decoder_under_loss_and_corruption (__main__.TestCrossLanguageCompatibility)
  AssertionError: b"W\x01\x93Z\x9b\xb2\x13\x1d$\xf2\xf7\xf0..." != b'}\x89\xa7\xbak\xe3*!\xd7\x1ff\xd8%d\x90C...' : Data mismatch on JS->Python reconstruction for size=100
  ```
- **Finding**: Line 15 in `web/fountain.js` has `Math.imul(t ^ (t >>> 7), 61)` instead of `Math.imul(t ^ (t >>> 7), t | 61)`. Because of this missing `t |`, the JS Mulberry32 produces completely different random state transitions than Python Mulberry32 for every seed. When non-systematic packets (`seed >= K`) are sent over the air-gap (e.g. when packets are lost), the JS receiver assumes incorrect droplet block indices, feeding wrong equations into the incremental GF(2) Gaussian elimination solver and failing or corrupting data reconstruction.

---

### Observation 1.2: Reconstructed Payload Slicing Bug in Python Receivers
- **Files**:
  - `/home/henry/Documents/Projects/Python/QR ChromaBeam/desktop_receiver/receiver_gui.py`, Line 188
  - `/home/henry/Documents/Projects/Python/QR ChromaBeam/desktop_app.py`, Line 186
- **Current Code**:
  ```python
  if meta:
      self.filename, self.filesize, _ = meta
      data = data[len(data) - self.filesize:]  # Extract actual payload
  ```
- **Verbatim Error in Test Run** (`adversarial_auto_density.py`):
  ```
  FAIL: test_python_receiver_rapid_mode_switching_and_stream_abort (__main__.TestAutoDensityRapidModeSwitching)
  AssertionError: b'\x0[84 chars]losslessly under rapid mode switching!\x00\x00\x00\x00\x00\x00' != b'\x0[84 chars]losslessly under rapid mode switching!'
  ```
- **Finding**: Slicing from the tail using `data[len(data) - self.filesize:]` assumes there is no trailing block padding in `data`. Because `LTDecoder.reconstruct_data()` returns `K * block_size` bytes, any file whose transfer stream length is not an exact multiple of `block_size` has trailing `b'\x00'` padding. The tail-slice grabs these trailing zeros and truncates the beginning of the file payload by the padding length.

---

### Observation 1.3: Crash on Empty Filename / IsADirectoryError in Python Receiver
- **File**: `/home/henry/Documents/Projects/Python/QR ChromaBeam/desktop_receiver/receiver_gui.py`, Line 190-191
- **Current Code**:
  ```python
  out_path = os.path.join(self.output_dir, self.filename)
  with open(out_path, "wb") as f:
      f.write(data)
  ```
- **Verbatim Error in Test Run** (`test_tracker.py`):
  ```
  ERROR: test_360_4way_rotation_invariance_all_modes (test_tracker.TestTrackerAndRotationInvariance)
  Traceback (most recent call last):
    File ".../tests/test_tracker.py", line 236, in test_360_4way_rotation_invariance_all_modes
      annotated, stats = receiver.process_frame(frame)
    File ".../desktop_receiver/receiver_gui.py", line 162, in process_frame
      self._save_reconstructed_file()
    File ".../desktop_receiver/receiver_gui.py", line 191, in _save_reconstructed_file
      with open(out_path, "wb") as f:
  IsADirectoryError: [Errno 21] Is a directory: '/tmp/chromabeam_downloads/'
  ```
- **Finding**: When random data or a header with empty filename (`""`) is received, `os.path.join('/tmp/chromabeam_downloads/', '')` evaluates to `'/tmp/chromabeam_downloads/'`. Opening this directory with `open(out_path, "wb")` crashes with `IsADirectoryError`.

---

### Observation 1.4: Protocol Metadata Unpacking Return Signature Discrepancy
- **Files**:
  - `/home/henry/Documents/Projects/Python/QR ChromaBeam/core/protocol.py`, Line 106
  - `/home/henry/Documents/Projects/Python/QR ChromaBeam/web/protocol.js`, Line 103
- **Finding**: In JS `web/protocol.js`, `unpackFileMetadata` returns `{ filename, filesize, mimeType, metadataHeaderLen }`. In Python `core/protocol.py`, `unpack_file_metadata` returns `(filename, filesize, mime_type)` without returning the header byte offset (`metadataHeaderLen`). This makes it impossible for Python receivers to accurately slice the payload from the front (`data[header_len : header_len + filesize]`).

---

### Observation 1.5: Positive Observations (Robust Modules)
- **Offline HTML Single-File Bundle (`chromabeam_offline.html`)**:
  - 100% self-contained (135,093 bytes).
  - Contains ZERO external URLs, CDNs, external scripts, or external stylesheets.
  - Passes full zero-network offline air-gap compliance.
- **Embedded Web Worker (`scanner_worker.js`)**:
  - Compiles cleanly in JavaScript VM without syntax or scope errors.
  - Correctly responds to `reset` and `processFrame` message protocols.
- **Color Matrix Engine Parity**:
  - Mode 0 (1-bit B&W Potato), Mode 1 (2-bit 4-Color Balanced), and Mode 2 (3-bit 8-Color Turbo) bit-packing and coordinate mappings are 100% identical between Python `core/color_matrix.py` and JS `web/matrix.js`.
  - Concentric 1:1:1:1:1 anchor centers $(2.5/N, 2.5/N)$ and white center dots match across all densities (32, 48, 64).

---

## 2. Logic Chain

1. From **Observation 1.1**, `web/fountain.js` line 15 defines Mulberry32 as `t ^= (t + Math.imul(t ^ (t >>> 7), 61)) >>> 0;` missing `t | 61`.
2. As a direct result, any droplet with `seed >= K` generates different block index sets in JS vs Python.
3. Therefore, cross-language recovery across optical air-gaps fails whenever packet loss occurs (since fountain recovery depends on `seed >= K`).
4. From **Observation 1.2**, `desktop_receiver/receiver_gui.py` and `desktop_app.py` slice payload using `data[len(data) - self.filesize:]`.
5. Because `data` has length `K * block_size` (including trailing padding zeros), slicing from the back includes the padding zeros and truncates the file's header bytes.
6. Therefore, file transfers to Python desktop receivers produce corrupted files with prepended corruption and appended zeros whenever file size is not an exact multiple of block size.
7. From **Observation 1.3**, when `self.filename` is empty or invalid, `_save_reconstructed_file` attempts to open `/tmp/chromabeam_downloads/` as a file, causing an unhandled `IsADirectoryError` crash.
8. Therefore, the system cannot be approved until these cross-language and reconstruction defects are resolved.

---

## 3. Caveats

- **Webcam Hardware Drivers**: Physical webcam driver quirks and rolling shutter artifacts were tested via extensive OpenCV synthetic distortion/loopback models and simulated Web Worker frame buffers rather than physical USB hardware.
- **Node.js Environment**: Cross-language testing was evaluated against Node.js v22.23.2 runtime mimicking browser V8 Web Worker execution.

---

## 4. Conclusion

**Verdict: `REQUEST_CHANGES`**

### Required Action Items:

1. **Fix Mulberry32 PRNG in `web/fountain.js`**:
   Change line 15 in `web/fountain.js`:
   ```javascript
   // Old:
   t ^= (t + Math.imul(t ^ (t >>> 7), 61)) >>> 0;
   // New:
   t ^= (t + Math.imul(t ^ (t >>> 7), t | 61)) >>> 0;
   ```
   And re-bundle `chromabeam_offline.html` using `python build_offline_html.py`.

2. **Fix `unpack_file_metadata` in `core/protocol.py`**:
   Update `unpack_file_metadata` to return the header length (or provide a helper `unpack_file_payload(data: bytes) -> Tuple[str, int, str, bytes]`):
   ```python
   def unpack_file_metadata(data: bytes) -> Optional[Tuple[str, int, str, int]]:
       if len(data) < 6:
           return None
       filesize, name_len = struct.unpack_from(">IB", data, 0)
       offset = 5
       if len(data) < offset + name_len + 1:
           return None
       filename = data[offset:offset + name_len].decode('utf-8', errors='replace')
       offset += name_len
       mime_len = data[offset]
       offset += 1
       if len(data) < offset + mime_len:
           return None
       mime_type = data[offset:offset + mime_len].decode('utf-8', errors='replace')
       header_len = offset + mime_len
       return filename, filesize, mime_type, header_len
   ```

3. **Fix Payload Extraction & Directory Error in Python Receivers (`desktop_receiver/receiver_gui.py` and `desktop_app.py`)**:
   In `desktop_receiver/receiver_gui.py`:
   ```python
   def _save_reconstructed_file(self):
       data = self.decoder.reconstruct_data()
       if data:
           meta = unpack_file_metadata(data)
           if meta:
               filename, self.filesize, _, header_len = meta
               self.filename = filename.strip() or "received_file.bin"
               data = data[header_len:header_len + self.filesize]
           else:
               self.filename = "received_file.bin"

           os.makedirs(self.output_dir, exist_ok=True)
           out_path = os.path.join(self.output_dir, self.filename)
           with open(out_path, "wb") as f:
               f.write(data)
           print(f"[ChromaBeam] File successfully saved to: {out_path}")
   ```
   Apply the identical fix to `desktop_app.py` line 181-190.

---

## 5. Verification Method

To independently reproduce and verify these findings:

```bash
# 1. Run cross-language adversarial test suite
/home/henry/Documents/Projects/Python/venv/bin/python .agents/teamwork_preview_challenger_2/adversarial_cross_lang.py

# 2. Run offline bundle & worker lifecycle test suite
/home/henry/Documents/Projects/Python/venv/bin/python .agents/teamwork_preview_challenger_2/test_offline_bundle_adversarial.py

# 3. Run auto-density & rapid mode switching test suite
/home/henry/Documents/Projects/Python/venv/bin/python .agents/teamwork_preview_challenger_2/adversarial_auto_density.py

# 4. Run existing test suite demonstrating tracker directory crash
/home/henry/Documents/Projects/Python/venv/bin/python -m unittest tests/test_tracker.py
```
