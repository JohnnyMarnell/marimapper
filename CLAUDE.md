# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MariMapper is a Python tool that maps addressable LEDs to 2D/3D space using computer vision and structure-from-motion (SFM). It uses a webcam to capture LED positions from multiple views, then reconstructs their 3D coordinates using pycolmap.

**Key constraint**: pycolmap==3.11.1 is pinned because 2-track reconstruction is broken in newer versions (see issue #79).

## Development Commands

### Environment Setup

**For end users** (installing as a tool):
```bash
uv tool install git+https://github.com/TheMariday/marimapper
```

**For developers** (working on cloned repo):
```bash
# 1. Clone with submodules (includes test data)
git clone --recurse-submodules https://github.com/TheMariday/marimapper
# OR if already cloned: git submodule update --init --recursive

# 2. Create and activate virtual environment
# Using UV (recommended)
uv venv                          # Create virtual environment
source .venv/bin/activate        # Activate (Linux/Mac)
# OR: .venv\Scripts\activate     # Activate (Windows)
uv pip install -e '.[develop]'  # Install in editable mode with dev dependencies
                                 # Note: quotes needed for zsh shell

# Using pip
python -m venv .venv
source .venv/bin/activate
pip install -e '.[develop]'
```

After installing in editable mode, changes to the code take effect immediately without reinstalling.

### Testing

**IMPORTANT**: Tests require the test data submodule. Initialize it first:
```bash
git submodule update --init --recursive
```

```bash
# Run all tests
pytest .

# Run specific test file
pytest test/test_led_identifier.py

# Run with coverage
pytest --cov=marimapper --cov-report=html .
```

### Linting and Formatting
```bash
# Check syntax errors
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Check all linting warnings
flake8 . --count --statistics

# Format code with black
black .

# Check formatting without changes
black . --check
```

### Running CLI Tools
```bash
# Check camera compatibility
marimapper_check_camera

# Check backend functionality
marimapper_check_backend <backend_name>

# Run the scanner (main tool)
marimapper <backend_name> [options]

# Upload map to PixelBlaze
marimapper_upload_mapping_to_pixelblaze
```

## Architecture

### Multi-Process Pipeline
MariMapper uses a multi-process architecture with queues for communication:

1. **DetectorProcess** (`detector_process.py`): Controls camera, enables LEDs one-by-one via backend, detects LED positions in 2D
2. **SFM Process** (`sfm_process.py`): Receives 2D LED positions, runs structure-from-motion reconstruction to create 3D map
3. **VisualiseProcess** (`visualize_process.py`): Displays real-time 3D reconstruction using Open3D
4. **FileWriterProcess** (`file_writer_process.py`): Writes 2D and 3D maps to CSV files

The **Scanner** class (`scanner.py`) orchestrates these processes, connecting them via output/input queues.

### Critical Multiprocessing Note
**MUST use `spawn` start method** (not `fork`) due to Open3D's `estimate_normals()` causing crashes on Linux with fork. This is set in:
- `scanner.py`: Called at Scanner init
- `conftest.py`: Pytest fixture ensures spawn for all tests

See issue #46 for details.

### Backend System
Backends control LED hardware. All backends must implement:
```python
class Backend:
    def get_led_count(self) -> int
    def set_led(self, led_index: int, on: bool) -> None
```

Backend registration happens in `backends/backend_utils.py`:
- `backend_factories`: Maps backend name to factory function
- `backend_arg_setters`: Maps backend name to argparse setup function

Supported backends: fadecandy, fcmega, wled, pixelblaze, artnet, custom, dummy

### SFM Reconstruction Flow
1. Camera captures LED positions across multiple views (minimum 2 views required)
2. 2D positions stored as `LED2D` objects with view IDs
3. `sfm()` function creates temporary database, populates it with camera model and LED observations
4. pycolmap's `incremental_mapping()` reconstructs 3D positions
5. Results converted to `LED3D` objects with positions and normals
6. Gap filling/interpolation applied based on `--interpolation-max-fill` and `--interpolation-max-error` parameters

Key files:
- `sfm.py`: Core reconstruction algorithm
- `database_populator.py`: Creates COLMAP database from 2D observations
- `model.py`: Converts COLMAP binary output to LED3D objects
- `led.py`: LED2D/LED3D data structures and utilities

## Understanding the Scan Process

### Overview: How Multi-View Scanning Works

MariMapper uses **Structure-from-Motion (SFM)** to reconstruct 3D LED positions from 2D camera images. This requires viewing LEDs from multiple angles, similar to how your two eyes create depth perception.

**The key to 3D mapping: Move the camera between scans, NOT during scans.**

### User Workflow: Camera Movement is Required

**CRITICAL**: To create 3D maps, you MUST physically move the camera between scans. Each scan captures LEDs from a different viewing angle, which enables 3D reconstruction through triangulation.

**Scanning Workflow:**
1. **First Position**: Set up camera in a stable position (tripod recommended)
   - Ensure camera won't move during the scan
   - Remove all light sources from view (tape over power LEDs)
   - Run: `marimapper <backend>`
   - Type `y` to start first scan
   - **DO NOT MOVE camera or LEDs during capture**

2. **Move Camera**: After first scan completes
   - **Move camera to new position** (6-20° rotation recommended)
   - Keep most LEDs in view (some overlap required)
   - Ensure camera is stable again

3. **Additional Scans**: Repeat from different angles
   - Type `y` to start next scan
   - DO NOT MOVE during capture
   - Move camera after each scan completes
   - Minimum 2 views required for 3D, recommend 3-5 views

4. **Reconstruction**: SFM automatically combines all views
   - 3D visualization window appears after successful reconstruction
   - Add more scans to improve quality

**Key Rules:**
- ✅ Move camera BETWEEN scans (after each completes)
- ❌ DO NOT move camera DURING a scan
- ✅ Overlap views by >50% (keep most LEDs visible)
- ❌ Don't move camera >20° at once (may lose overlap)
- ✅ Use stable mounting (tripod)
- ❌ Don't move the physical LEDs themselves

**2D vs 3D Maps:**
- **Single scan** (one view): Creates only 2D map (`led_map_2d_<timestamp>.csv`). Useful for 2D LED strips/grids.
- **Multiple scans** (2+ views): Creates both 2D maps AND 3D map (`led_map_3d.csv`). Required for 3D LED structures.
- **Structure-from-Motion (SFM)** needs minimum 2 different viewing angles to calculate depth/3D positions through triangulation.

### End-to-End Workflow

MariMapper uses an **incremental scanning approach** where each scan adds more 2D observations, improving the overall 3D reconstruction:

```
User runs: marimapper <backend>
    ↓
Scanner loads existing 2D maps (if any)
    ↓
Scanning Loop (repeat for multiple views):
  1. User confirms "Start scan?"
  2. DetectorProcess captures LED positions (2D coordinates)
     → Sends to SFM, FileWriter, Visualizer via queues
  3. SFM Process reconstructs 3D positions:
     - Populates COLMAP database with all 2D points (old + new)
     - Runs pycolmap incremental_mapping
     - Merges duplicate detections from overlapping views
     - Fills gaps between consecutive LEDs
     - Computes surface normals
  4. FileWriter writes 2D view CSV when scan completes
  5. FileWriter continuously updates 3D CSV with latest reconstruction
  6. Visualizer shows real-time status (colors indicate reconstruction quality)
    ↓
Final output:
  - Multiple 2D CSVs (one per view)
  - Single 3D CSV (merged reconstruction from all views)
```

**Key insight**: Each new scan doesn't replace previous work—it adds more viewing angles to improve the combined 3D model.

### File Handling

#### 2D Map Files (Per-View Detections)
- **Pattern**: `led_map_2d_<YYYYMMDD-HHMMSS>.csv`
- **Content**: `index,u,v` (LED index, x pixel coordinate, y pixel coordinate)
- **Created**: One file per scan/view when DetectorProcess completes
- **Loading**: On scanner init, `get_all_2d_led_maps()` (in `file_utils.py`) loads ALL existing 2D CSVs from the output directory in alphabetical order. Each file gets assigned a view ID based on file order.

#### 3D Map File (Merged Reconstruction)
- **Name**: `led_map_3d.csv` (single file, constantly overwritten)
- **Content**: `index,x,y,z,xn,yn,zn,error`
  - `x,y,z`: 3D position coordinates
  - `xn,yn,zn`: Surface normal vector
  - `error`: Reprojection error (quality metric)
- **Updated**: Every time SFM reconstruction completes (continuously improves as more views added)
- **Merging**: Not merged—replaced with latest reconstruction combining ALL 2D observations

#### Multi-Scan Strategy
1. First scan creates initial 2D CSV file
2. Scanner loads this 2D file on next run as "existing_leds"
3. Second scan creates new 2D CSV file
4. SFM reconstruction uses BOTH files together (all views)
5. Result: Single improved 3D map incorporating all viewing angles

### Common Log Messages Explained

| Log Message | Meaning | Source File |
|-------------|---------|-------------|
| `Populating sfm database with 576 leds` | Creating COLMAP database with 576 total 2D LED observations across all views before reconstruction. | `database_populator.py:64` |
| `Reconstructing science...` | SFM process is running pycolmap reconstruction algorithm. | `sfm_process.py:42` |
| `merged 31 leds` | Found 31 duplicate LED reconstructions (from overlapping views) and averaged them into single positions. Indicates successful multi-view consolidation. | `led.py:317` |
| `sfm managed to reconstruct 31 leds in map 0` | pycolmap successfully calculated 3D positions for 31 LEDs. "map 0" is the primary reconstruction (COLMAP can produce multiple disconnected maps). | `sfm.py:69` |
| `filled 1 LEDs` | Gap-filling interpolated 1 missing LED between two reconstructed LEDs based on distance constraints (`--interpolation-max-fill` and `--interpolation-max-error`). | `led.py:279` |
| `Reconstructed X (backend reported: Y, scan range: Z) in A seconds (post process took B seconds)` | **X** = LEDs successfully reconstructed (KEY NUMBER!), **Y** = actual LED count from backend (e.g., "Pixelblaze reports 50 pixels"), **Z** = scan range (end - start, default 10000), **A** = pycolmap reconstruction time, **B** = post-processing time. Compare X to Y to see reconstruction success rate. Appears at startup if existing LED files found (reconstructing previous scans) and after each new scan. | `sfm_process.py:185` |
| `Scan X has overlap of Y points or Z%` | New scan shares Y LED detections with existing model (Z% of new scan). <50% overlap may cause scan to be ignored. | `sfm.py` |
| `Warning! Scan X has very low overlap...` | Camera moved too far between scans (<10% LEDs visible in both views). This scan may be ignored. Add intermediate scans to bridge the gap, or reposition camera closer to previous view. | `sfm.py` |

**What Good Logs Look Like:**
- High LED count in database (hundreds of observations)
- Reconstructed count close to total LED count
- Some merging/filling is normal (indicates overlapping views)
- Overlap >50% on subsequent scans

### Verifying Multi-Scan Success

#### File-Based Verification
```bash
# Check how many views/scans were captured
ls -lt output_dir/led_map_2d_*.csv
# Each file = one view; should see multiple timestamped files

# Check 3D map is recent and non-empty
ls -lh output_dir/led_map_3d.csv
wc -l output_dir/led_map_3d.csv  # Count rows (subtract 1 for header)
```

#### Console Output Verification
After each scan completes, SFM prints:
```
Reconstructed X / Y in Z seconds
```
- `X` = LEDs with 3D positions (should increase with each scan)
- `Y` = Total LEDs scanned
- Target: X/Y ratio >90% for good coverage

#### Visualization Verification
The real-time 3D viewer shows LED status by color:
- **Green**: Reconstructed (reliable, 2+ views)
- **Cyan**: Interpolated/merged (acceptable)
- **Orange**: Only detected in 1 view (needs more angles)
- **Red**: Detected in 2+ views but can't triangulate (calibration issue)
- **Black**: Not detected at all

### Checking LED Detection Reliability

#### Reconstruction Quality Metrics

1. **Reconstruction Percentage**:
   ```bash
   # Count reconstructed LEDs (subtract 1 for header)
   wc -l led_map_3d.csv

   # Calculate: (reconstructed / total_led_count) × 100
   # Target: >90% for good scans
   ```

2. **Per-LED Error Values**:
   ```bash
   # Find high-error LEDs (error > 1.0 pixels)
   awk -F',' 'NR>1 && $NF > 1.0 {print $1, $NF}' led_map_3d.csv

   # Good quality: errors consistently <0.5
   # Acceptable: errors <1.0
   # Problematic: errors >2.0
   ```

3. **Scan Overlap Percentage**:
   - Look for `"Scan X has overlap of Y or Z%"` in logs
   - **>50% overlap**: Safe, will contribute to reconstruction
   - **10-50% overlap**: Marginal, may work
   - **<10% overlap**: Warning shown, likely ignored

#### LED Status Categories (from `LEDInfo` enum in `led.py`)

| Status | Color | Reliability | Meaning |
|--------|-------|-------------|---------|
| `RECONSTRUCTED` | Green | High | Position from 2+ views, well-triangulated |
| `MERGED` | Cyan | High | Multiple detections averaged together |
| `INTERPOLATED` | Cyan | Medium | Gap-filled between neighbors |
| `DETECTED` | Orange | Low | Only 1 view detected it |
| `UNRECONSTRUCTABLE` | Red | Failed | 2+ views but can't triangulate (geometry issue) |
| `NONE` | Black | Failed | Not detected in any view |

#### Verification Checklist
- [ ] All expected LED indices present in 3D CSV
- [ ] Reconstruction percentage >90%
- [ ] Few or no high-error values (check error column)
- [ ] Gap-filling count reasonable (1-5% of total)
- [ ] All scans showed >50% overlap
- [ ] Minimal red dots in visualization
- [ ] 3D model visually matches physical LED layout

### Identifying and Interpolating Missing LEDs

#### Visualization: Color-Coded LED Status

The 3D visualizer shows LED reconstruction status using color codes (from `led.py:85-96`):

| Color | LED Status | What It Means |
|-------|------------|---------------|
| 🟢 **Green** | `RECONSTRUCTED` | Successfully triangulated from 2+ views (reliable) |
| 🔵 **Cyan/Aqua** | `INTERPOLATED` or `MERGED` | Gap-filled between neighbors OR merged from duplicate detections |
| 🟠 **Orange** | `DETECTED` | Only detected in 1 view (can't triangulate, needs more angles) |
| 🔴 **Red** | `UNRECONSTRUCTABLE` | Detected in 2+ views but can't triangulate (camera calibration issue) |
| **Blue** | `NONE` | Not detected in any view (missing) |

**To identify missing LEDs visually:**
1. Run scan and wait for 3D viewer window to appear
2. Look for **blue dots** (not detected) or **orange dots** (only 1 view)
3. Orange/blue dots indicate LEDs that need more viewing angles
4. Add more scans from different positions to capture these LEDs

#### Automatic Gap Filling (Interpolation)

MariMapper can automatically interpolate positions for missing LEDs if they fall between two reconstructed LEDs with consistent spacing.

**CLI Parameters:**
```bash
marimapper <backend> \
  --interpolation_max_fill 5 \      # Max consecutive missing LEDs to interpolate (default: 5)
  --interpolation_max_error 0.2      # Max spacing variance tolerance (default: 0.2 = ±20%)
```

**How It Works** (`led.py:249-281`):
1. After 3D reconstruction, `fill_gaps()` scans for missing LED indices
2. If LEDs are missing between two reconstructed LEDs (e.g., LED 10 and LED 15 are present, but 11-14 are missing):
   - Calculates expected spacing: `distance / (gap + 1)`
   - Checks if spacing is consistent: `1.0 - max_error < spacing < 1.0 + max_error`
   - If gap ≤ `max_fill` and spacing is consistent, creates interpolated LEDs
   - Interpolated positions are linearly distributed between the two anchors
3. Interpolated LEDs are marked with `interpolated=True` flag (appear cyan in visualizer)
4. Log shows: `"filled X LEDs"` when interpolation succeeds

**Examples:**
```bash
# No interpolation (disable gap filling)
marimapper pixelblaze --interpolation_max_fill 0

# Conservative interpolation (only fill 1-2 missing LEDs)
marimapper pixelblaze --interpolation_max_fill 2 --interpolation_max_error 0.1

# Aggressive interpolation (fill up to 10 missing LEDs, relaxed spacing)
marimapper pixelblaze --interpolation_max_fill 10 --interpolation_max_error 0.5
```

**When to adjust these parameters:**
- **Uniform LED strips** (equal spacing): Use higher `max_fill` (10+) and tighter `max_error` (0.1)
- **Irregular spacing**: Disable interpolation (`max_fill=0`) or use very low values
- **Noisy detections**: Tighten `max_error` to avoid bad interpolations
- **High missing rate**: Add more scans from different angles instead of relying on interpolation

#### Finding Missing LEDs in CSV Files

**Check 3D map for missing indices:**
```bash
# List all LED indices in 3D map
awk -F',' 'NR>1 {print $1}' led_map_3d.csv | sort -n

# Find missing indices (if you expect 0-99)
comm -23 <(seq 0 99) <(awk -F',' 'NR>1 {print $1}' led_map_3d.csv | sort -n)

# Count how many LEDs are present
wc -l led_map_3d.csv  # Subtract 1 for header
```

**Identify LEDs by reconstruction type:**

The 3D CSV doesn't explicitly label interpolated LEDs, but you can infer from the data:
- Check which indices exist in 2D maps but not 3D map → `DETECTED` (orange, only 1 view)
- Check which indices don't exist in any 2D map → `NONE` (blue, never detected)
- Interpolated LEDs will have perfect linear positions between neighbors

**Systematic approach to fix missing LEDs:**
1. **Run scan** → Check 3D viewer for orange/blue dots
2. **Note positions** of missing LEDs (use LED indices from visualization)
3. **Reposition camera** to view missing LEDs from different angle
4. **Run another scan** → Missing LEDs should turn green if now visible
5. **Check logs** for `"filled X LEDs"` to see if gap-filling helped
6. **Verify in CSV** that all expected indices are present

#### Visualizer Controls for Inspection

When viewing the 3D model (mentioned in README.md):
- **Click and drag**: Rotate model to see all angles
- **Scroll wheel**: Zoom in/out to inspect specific LEDs
- **Shift + drag**: Roll camera
- **`n` key**: Toggle normals (arrows showing surface direction)
- **`+` / `-` keys**: Increase/decrease point size (easier to see individual LEDs)
- **`1`, `2`, `3`, `4` keys**: Change color scheme (default is `1` showing reconstruction status)

Use these controls to closely inspect blue/orange LEDs and plan where to position camera for next scan.

### Camera Model
Default camera model is `camera_model_radial` with 60° FOV. Can be changed via `--camera-model` CLI argument. Camera models defined in `database_populator.py`.

### Exposure Control Limitation
Exposure control not supported on macOS (issue #51). Users must adjust exposure manually via third-party tools.

## Code Exclusions

The following are excluded from Black formatting and test coverage:
- `marimapper/pycolmap_tools/*` (vendored COLMAP utilities)
- `marimapper/backends/*` (coverage exclusion only)
- `marimapper/scripts/*` (coverage exclusion only)

## Writing a New Backend

1. Create directory: `marimapper/backends/mybackend/`
2. Create `__init__.py` and `mybackend_backend.py`
3. Implement factory function and arg setter:
   ```python
   def mybackend_backend_factory(args):
       return partial(Backend, args.param1, args.param2)

   def mybackend_backend_set_args(parser):
       parser.add_argument("--param1", default="value")
   ```
4. Implement Backend class with `get_led_count()` and `set_led()`
5. Register in `backends/backend_utils.py`
6. Add documentation to `docs/backends/MyBackend.md`

## Supported Python Versions
Python 3.9, 3.10, 3.11, 3.12 (not 3.13+)

## License
GPLv3 - all derivative works must be open source
