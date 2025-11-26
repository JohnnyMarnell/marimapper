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
