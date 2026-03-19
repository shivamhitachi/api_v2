# #!/usr/bin/env python3
# import os
# import glob
# import json
# from datetime import timedelta
#
# import numpy as np
# import pandas as pd
# import xarray as xr
# from PIL import Image
#
# # =========================
# # ======= CONFIG ==========
# # =========================
#
# # Input discovery
# DEFAULT_INPUT_DIR = "/data_drive/stormcast_10ens_7days/fcn3_stormcast/2026-01-02_24h/"
# DEFAULT_PATTERN_PRIMARY = "fcn3_member_*.zarr"
# DEFAULT_PATTERN_FALLBACK = "*.zarr"
#
# # Output root derives from the last component of DEFAULT_INPUT_DIR
# DATE_TAG = os.path.basename(os.path.normpath(DEFAULT_INPUT_DIR))  # e.g., "2026-01-02_24h"
# OUTPUT_ROOT = os.path.join("./e2cc_outputs", DATE_TAG)
#
# # Variables to visualize (separate folder per variable)
# VARIABLES = ["t2m", "mslp", "u10m", "v10m"]
#
# # Optional vertical level (e.g., 500 for 500 hPa); None uses first if present
# LEVEL = None
#
# # Which initialization time index to use if there are multiple
# TIME_INDEX = 0
#
# # Normalization mode: "fixed" | "percentile" | "auto"
# VMODE = "percentile"
# VMIN, VMAX = None, None     # used when VMODE="fixed"
# PMIN, PMAX = 1.0, 99.0      # used when VMODE="percentile"
#
# # Optional unit conversion: "none" or "kelvin_to_celsius"
# UNIT_CONVERSION = "none"
#
# # Image settings (JPEG only; E2CC requires JPEG)
# ALPHA_VALUE = 0.5           # valid-pixel opacity in [0..1]; NaNs become fully transparent
# JPEG_QUALITY = 95
# JPEG_SUBSAMPLING = 0        # 0 = no chroma subsampling (sharper)
# JPEG_OPTIMIZE = True
#
# # Viewer hint (e2cc may colorize grayscale with this colormap)
# COLORMAP = "coolwarm"
#
# # =========================
# # ====== END CONFIG =======
# # =========================
#
#
# def open_zarr_any(zarr_path: str) -> xr.Dataset:
#     try:
#         return xr.open_zarr(zarr_path, consolidated=True)
#     except Exception:
#         return xr.open_zarr(zarr_path, consolidated=False)
#
#
# def detect_level_dim(var: xr.DataArray):
#     for cand in ("level", "isobaricInhPa", "pressure", "plev"):
#         if cand in var.dims:
#             return cand
#     return None
#
#
# def normalize_data(data, vmin=None, vmax=None):
#     arr = np.asarray(data)
#     if vmin is None:
#         vmin = np.nanmin(arr)
#     if vmax is None:
#         vmax = np.nanmax(arr)
#     if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax == vmin:
#         return np.zeros_like(arr, dtype=np.float32), vmin, vmax
#     norm = (arr - vmin) / (vmax - vmin)
#     return np.clip(norm, 0, 1).astype(np.float32), vmin, vmax
#
#
# def to_grayscale_u8(norm01):
#     return (np.clip(norm01, 0, 1) * 255).astype(np.uint8)
#
#
# def alpha_from_nan(data, alpha_value=0.5):
#     base = int(alpha_value * 255)
#     return np.where(np.isnan(data), 0, base).astype(np.uint8)
#
#
# def guess_time_coords(ds: xr.Dataset):
#     t_candidates = ["time", "initial_time", "forecast_reference_time"]
#     lt_candidates = ["lead_time", "step", "forecast_hour", "fhour"]
#     t_name = next((c for c in t_candidates if c in ds.coords), None)
#     lt_name = next((c for c in lt_candidates if c in ds.coords), None)
#     if t_name is None or lt_name is None:
#         raise KeyError(f"Could not find time/lead_time coords. Found coords: {list(ds.coords)}")
#     return t_name, lt_name
#
#
# def parse_base_time(ds: xr.Dataset, t_name: str):
#     t0 = ds.coords[t_name].values[0]
#     return pd.Timestamp(t0).to_pydatetime()
#
#
# def compute_bounds(ds: xr.Dataset):
#     if {"lat", "lon"}.issubset(ds.coords):
#         lat = ds["lat"].values
#         lon = ds["lon"].values
#         return [float(np.nanmin(lat)), float(np.nanmin(lon))], [float(np.nanmax(lat)), float(np.nanmax(lon))]
#     # fallback (global)
#     return [-90.0, -180.0], [90.0, 180.0]
#
#
# def format_ts(dt):
#     return dt.strftime("%Y-%m-%dT%H-%M-%S")
#
#
# def format_key(dt):
#     return dt.strftime("%Y-%m-%dT%H:%M:%S")
#
#
# def apply_unit_conversion(arr, conversion: str):
#     if conversion == "kelvin_to_celsius":
#         return arr - 273.15
#     return arr
#
#
# def choose_inputs():
#     # Primary pattern
#     paths = sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_PRIMARY)))
#     if paths:
#         return paths
#     # Fallback pattern
#     paths = sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_FALLBACK)))
#     # Keep directories only
#     paths = [p for p in paths if os.path.isdir(p)]
#     if paths:
#         return paths
#     raise FileNotFoundError(
#         f"No Zarr inputs found.\n"
#         f"Tried: {os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_PRIMARY)} and {os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_FALLBACK)}.\n"
#         f"Place your FCN3 .zarr in '{DEFAULT_INPUT_DIR}' or adjust DEFAULT_INPUT_DIR."
#     )
#
#
# def render_one_zarr(input_zarr: str, variable: str):
#     print(f"\n[INFO] Loading FCN3 Zarr: {input_zarr}")
#     ds = open_zarr_any(input_zarr)
#
#     if variable not in ds.data_vars:
#         raise ValueError(f"Variable '{variable}' not found in {input_zarr}. Available: {list(ds.data_vars)}")
#
#     var = ds[variable]
#
#     # Optional vertical level selection
#     lev_dim = detect_level_dim(var)
#     if lev_dim and LEVEL is not None:
#         lev_vals = var[lev_dim].values
#         idx = int(np.argmin(np.abs(lev_vals - float(LEVEL))))
#         sel_level_val = lev_vals[idx]
#         print(f"[INFO] Selecting {lev_dim}={sel_level_val}")
#         var = var.sel({lev_dim: sel_level_val})
#     elif lev_dim and LEVEL is None:
#         print(f"[WARN] '{variable}' has vertical dim '{lev_dim}'. Using the first level. "
#               f"To change, set LEVEL in CONFIG.")
#         var = var.isel({lev_dim: 0})
#
#     # Discover time + lead time
#     t_name, lt_name = guess_time_coords(ds)
#     base_time = parse_base_time(ds, t_name)
#     print(f"[INFO] Base time ({t_name}): {base_time.isoformat()}")
#
#     # Limit to a single initialization if var carries time dim
#     if t_name in var.dims:
#         var = var.isel({t_name: TIME_INDEX})
#
#     # Decide normalization bounds on the chosen init
#     range_source = var
#     tmp_vals = apply_unit_conversion(range_source.values, UNIT_CONVERSION)
#
#     if VMODE == "fixed":
#         vmin, vmax = VMIN, VMAX
#         print(f"[INFO] Using FIXED vmin/vmax: {vmin}, {vmax}")
#     elif VMODE == "percentile":
#         vmin = float(np.nanpercentile(tmp_vals, PMIN))
#         vmax = float(np.nanpercentile(tmp_vals, PMAX))
#         print(f"[INFO] Using PERCENTILES pmin={PMIN}, pmax={PMAX} -> vmin={vmin:.3f}, vmax={vmax:.3f}")
#     else:
#         vmin = float(np.nanmin(tmp_vals))
#         vmax = float(np.nanmax(tmp_vals))
#         print(f"[INFO] Using AUTO global range -> vmin={vmin:.3f}, vmax={vmax:.3f}")
#
#     # Output directory
#     zarr_leaf = os.path.basename(input_zarr.rstrip("/")).replace(".zarr", "")
#     base_leaf = f"{format_ts(base_time)}_{variable}" + (f"_{LEVEL}hPa" if lev_dim and LEVEL is not None else "")
#     out_dir = os.path.join(OUTPUT_ROOT, variable, zarr_leaf, base_leaf)
#     os.makedirs(out_dir, exist_ok=True)
#     print(f"[INFO] Output directory: {out_dir}")
#
#     # Bounds for e2cc config
#     latlon_min, latlon_max = compute_bounds(ds)
#
#     # Iterate forecast lead times
#     lead_vals = ds.coords[lt_name].values
#     sources, alpha_sources = {}, {}
#
#     # Units metadata
#     units = ds[variable].attrs.get("units", "")
#     if UNIT_CONVERSION == "kelvin_to_celsius":
#         units = "C"
#
#     for i, lt in enumerate(lead_vals):
#         # Compute valid time
#         if isinstance(lt, np.timedelta64) or "timedelta64" in str(type(lt)):
#             hours = pd.to_timedelta(lt).total_seconds() / 3600.0
#         else:
#             hours = float(np.asarray(lt))
#         valid_time = base_time + timedelta(hours=hours)
#
#         # Extract slice
#         if lt_name in var.dims:
#             slice_da = var.isel({lt_name: i})
#         else:
#             slice_da = var  # if var only has spatial dims
#
#         data = apply_unit_conversion(slice_da.values, UNIT_CONVERSION)
#
#         # Normalize and convert to images
#         norm01, _, _ = normalize_data(data, vmin, vmax)
#         gray = to_grayscale_u8(norm01)
#         alpha = alpha_from_nan(data, ALPHA_VALUE)
#
#         if gray.ndim != 2:
#             raise ValueError(f"Expected 2D field; got shape {gray.shape}. "
#                              f"Check variable/LEVEL/TIME_INDEX for {variable}.")
#
#         # Filenames (JPEG only)
#         stamp = format_ts(valid_time)
#         rgb_fn = f"{stamp}_rgb.jpeg"
#         alpha_fn = f"{stamp}_alpha.jpeg"
#
#         # Save RGB (3‑channel)
#         rgb_pil = Image.fromarray(gray, mode="L").convert("RGB")
#         rgb_pil.save(
#             os.path.join(out_dir, rgb_fn),
#             "JPEG",
#             quality=JPEG_QUALITY,
#             subsampling=JPEG_SUBSAMPLING,
#             optimize=JPEG_OPTIMIZE,
#         )
#
#         # Save alpha (grayscale JPEG). E2CC requires JPEG—no PNGs.
#         alpha_pil = Image.fromarray(alpha, mode="L")
#         alpha_pil.save(
#             os.path.join(out_dir, alpha_fn),
#             "JPEG",
#             quality=JPEG_QUALITY,
#             subsampling=JPEG_SUBSAMPLING,
#             optimize=JPEG_OPTIMIZE,
#         )
#
#         key = format_key(valid_time)
#         sources[key] = f"./{rgb_fn}"
#         alpha_sources[key] = f"./{alpha_fn}"
#
#         print(f"[OK] {variable}: {rgb_fn}  {alpha_fn}")
#
#     # Remapping metadata (viewer-side colorization)
#     remapping = {
#         "input_min": 0.0,
#         "input_max": 1.0,
#         "output_min": 0.0,
#         "output_max": 1.0,
#         "output_gamma": 0.75
#     }
#
#     config = {
#         "features": [{
#             "name": f"FCN3 - {variable}" + (f" @ {LEVEL} hPa" if LEVEL is not None else ""),
#             "type": "Image",
#             "projection": "latlong",
#             "sources": sources,
#             "alpha_sources": alpha_sources,
#             "latlon_min": latlon_min,
#             "latlon_max": latlon_max,
#             "remapping": remapping,
#             "colormap": COLORMAP,
#             "metadata": {
#                 "base_time": base_time.strftime("%Y-%m-%dT%H:%M:%S"),
#                 "variable": variable,
#                 "units": units,
#                 "vmin": vmin,
#                 "vmax": vmax
#             }
#         }]
#     }
#
#     with open(os.path.join(out_dir, "0000-config.json"), "w") as f:
#         json.dump(config, f, indent=2)
#
#     print(f"[DONE] {variable}: wrote {os.path.join(out_dir, '0000-config.json')}")
#
#     ds.close()
#
#
# def main():
#     os.makedirs(OUTPUT_ROOT, exist_ok=True)
#
#     # Discover inputs
#     inputs = sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_PRIMARY)))
#     if not inputs:
#         inputs = sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_FALLBACK)))
#         inputs = [p for p in inputs if os.path.isdir(p)]
#     if not inputs:
#         raise FileNotFoundError("No .zarr inputs found under DEFAULT_INPUT_DIR.")
#
#     print("[INFO] Found inputs:")
#     for p in inputs:
#         print("   ", p)
#
#     for p in inputs:
#         for var in VARIABLES:
#             render_one_zarr(p, var)
#
#     print("\n[ALL DONE] Open the generated folder(s) in e2cc.")
#
#
# if __name__ == "__main__":
#     main()


#!/usr/bin/env python3
"""FCN3 Zarr � E2CC JPEG Tiles & Config Generator

This script discovers FCN3 (Stormcast) Zarr inputs, renders selected variables as
grayscale JPEG tiles (RGB + alpha), and emits a per-variable `0000-config.json`
for use in an E2CC-style image viewer.

It supports:
- Automatic Zarr discovery via glob patterns
- Variable selection (with optional vertical `LEVEL`)
- Normalization modes: fixed range, percentiles, or auto-range
- Optional unit conversion (Kelvin � Celsius)
- JPEG output (with tunable quality/subsampling) and an alpha-plane JPEG
- Metadata (bounds, times, units, vmin/vmax) persisted into the config

Notes
-----
- This file adds **only** docstrings; no code changes elsewhere.
- Output is placed under: `./e2cc_outputs/<DATE_TAG>/<variable>/<zarr_leaf>/<base_leaf>/`.
"""

import os
import glob
import json
from datetime import timedelta

import numpy as np
import pandas as pd
import xarray as xr
from PIL import Image

# =========================
# ======= CONFIG ==========
# =========================

# Input discovery
DEFAULT_INPUT_DIR = "/data_drive/stormcast_10ens_7days/fcn3_stormcast/2026-01-02_24h/"
DEFAULT_PATTERN_PRIMARY = "fcn3_member_*.zarr"
DEFAULT_PATTERN_FALLBACK = "*.zarr"

# Output root derives from the last component of DEFAULT_INPUT_DIR
DATE_TAG = os.path.basename(os.path.normpath(DEFAULT_INPUT_DIR))  # e.g., "2026-01-02_24h"
OUTPUT_ROOT = os.path.join("./e2cc_outputs", DATE_TAG)

# Variables to visualize (separate folder per variable)
VARIABLES = ["t2m", "mslp", "u10m", "v10m"]

# Optional vertical level (e.g., 500 for 500 hPa); None uses first if present
LEVEL = None

# Which initialization time index to use if there are multiple
TIME_INDEX = 0

# Normalization mode: "fixed" | "percentile" | "auto"
VMODE = "percentile"
VMIN, VMAX = None, None     # used when VMODE="fixed"
PMIN, PMAX = 1.0, 99.0      # used when VMODE="percentile"

# Optional unit conversion: "none" or "kelvin_to_celsius"
UNIT_CONVERSION = "none"

# Image settings (JPEG only; E2CC requires JPEG)
ALPHA_VALUE = 0.5           # valid-pixel opacity in [0..1]; NaNs become fully transparent
JPEG_QUALITY = 95
JPEG_SUBSAMPLING = 0        # 0 = no chroma subsampling (sharper)
JPEG_OPTIMIZE = True

# Viewer hint (e2cc may colorize grayscale with this colormap)
COLORMAP = "coolwarm"

# =========================
# ====== END CONFIG =======
# =========================


def open_zarr_any(zarr_path: str) -> xr.Dataset:
    """
    Open a Zarr dataset, trying consolidated metadata first and falling back if needed.

    Parameters
    ----------
    zarr_path : str
        Filesystem path to a Zarr store directory.

    Returns
    -------
    xarray.Dataset
        The opened dataset.

    Notes
    -----
    - Uses `xr.open_zarr(..., consolidated=True)` first (fast if `.zmetadata` exists).
    - Falls back to `consolidated=False` when the consolidated metadata is unavailable.
    """
    try:
        return xr.open_zarr(zarr_path, consolidated=True)
    except Exception:
        return xr.open_zarr(zarr_path, consolidated=False)


def detect_level_dim(var: xr.DataArray):
    """
    Detect a vertical level dimension name if present in a DataArray.

    Parameters
    ----------
    var : xarray.DataArray
        Input array whose dims will be inspected.

    Returns
    -------
    str or None
        One of {"level", "isobaricInhPa", "pressure", "plev"} if found; otherwise None.
    """
    for cand in ("level", "isobaricInhPa", "pressure", "plev"):
        if cand in var.dims:
            return cand
    return None


def normalize_data(data, vmin=None, vmax=None):
    """
    Normalize data to [0, 1] given explicit or inferred min/max.

    Parameters
    ----------
    data : array-like
        Input numeric array.
    vmin : float, optional
        Minimum value for normalization. If None, uses `nanmin(data)`.
    vmax : float, optional
        Maximum value for normalization. If None, uses `nanmax(data)`.

    Returns
    -------
    tuple
        (norm01, vmin_used, vmax_used)
        - norm01 : numpy.ndarray, dtype float32
            Data normalized to [0, 1] with NaNs preserved.
        - vmin_used : float
        - vmax_used : float

    Notes
    -----
    - If vmin/vmax are not finite or equal, returns zeros of the same shape.
    """
    arr = np.asarray(data)
    if vmin is None:
        vmin = np.nanmin(arr)
    if vmax is None:
        vmax = np.nanmax(arr)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax == vmin:
        return np.zeros_like(arr, dtype=np.float32), vmin, vmax
    norm = (arr - vmin) / (vmax - vmin)
    return np.clip(norm, 0, 1).astype(np.float32), vmin, vmax


def to_grayscale_u8(norm01):
    """
    Convert a [0, 1] float array to uint8 grayscale in [0, 255].

    Parameters
    ----------
    norm01 : array-like
        Normalized array (values expected in [0, 1]).

    Returns
    -------
    numpy.ndarray
        Unsigned 8-bit grayscale image.
    """
    return (np.clip(norm01, 0, 1) * 255).astype(np.uint8)


def alpha_from_nan(data, alpha_value=0.5):
    """
    Build an 8-bit alpha plane where NaNs are fully transparent and valid pixels opaque.

    Parameters
    ----------
    data : array-like
        Source array; NaNs denote transparent pixels.
    alpha_value : float, optional
        Opaque alpha level for valid pixels in [0, 1]. Default is 0.5.

    Returns
    -------
    numpy.ndarray
        Alpha plane as uint8 (0..255), where NaNs map to 0.
    """
    base = int(alpha_value * 255)
    return np.where(np.isnan(data), 0, base).astype(np.uint8)


def guess_time_coords(ds: xr.Dataset):
    """
    Guess the names of the base time and lead time coordinates in a dataset.

    Parameters
    ----------
    ds : xarray.Dataset
        Input dataset whose coordinates will be inspected.

    Returns
    -------
    tuple
        (t_name, lt_name) where:
        - t_name : str
            One of {"time", "initial_time", "forecast_reference_time"}.
        - lt_name : str
            One of {"lead_time", "step", "forecast_hour", "fhour"}.

    Raises
    ------
    KeyError
        If no valid time and/or lead-time coordinates are found.
    """
    t_candidates = ["time", "initial_time", "forecast_reference_time"]
    lt_candidates = ["lead_time", "step", "forecast_hour", "fhour"]
    t_name = next((c for c in t_candidates if c in ds.coords), None)
    lt_name = next((c for c in lt_candidates if c in ds.coords), None)
    if t_name is None or lt_name is None:
        raise KeyError(f"Could not find time/lead_time coords. Found coords: {list(ds.coords)}")
    return t_name, lt_name


def parse_base_time(ds: xr.Dataset, t_name: str):
    """
    Parse the first initialization/base time as a Python datetime.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing the base time coordinate.
    t_name : str
        Name of the base/initial time coordinate.

    Returns
    -------
    datetime.datetime
        The first timestamp converted to a Python datetime.
    """
    t0 = ds.coords[t_name].values[0]
    return pd.Timestamp(t0).to_pydatetime()


def compute_bounds(ds: xr.Dataset):
    """
    Compute geographic bounds from dataset coordinates if available.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset potentially containing 'lat' and 'lon' coordinates.

    Returns
    -------
    tuple
        (latlon_min, latlon_max) where each is [lat, lon] as floats.
        If lat/lon are missing, returns global bounds: ([-90, -180], [90, 180]).
    """
    if {"lat", "lon"}.issubset(ds.coords):
        lat = ds["lat"].values
        lon = ds["lon"].values
        return [float(np.nanmin(lat)), float(np.nanmin(lon))], [float(np.nanmax(lat)), float(np.nanmax(lon))]
    # fallback (global)
    return [-90.0, -180.0], [90.0, 180.0]


def format_ts(dt):
    """
    Format a datetime for filenames (safe for filesystem paths).

    Parameters
    ----------
    dt : datetime.datetime
        Datetime to format.

    Returns
    -------
    str
        Timestamp formatted as '%Y-%m-%dT%H-%M-%S'.
    """
    return dt.strftime("%Y-%m-%dT%H-%M-%S")


def format_key(dt):
    """
    Format a datetime for JSON keys/metadata (ISO-like, colon-separated time).

    Parameters
    ----------
    dt : datetime.datetime
        Datetime to format.

    Returns
    -------
    str
        Timestamp formatted as '%Y-%m-%dT%H:%M:%S'.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def apply_unit_conversion(arr, conversion: str):
    """
    Apply optional unit conversion to a numeric array.

    Parameters
    ----------
    arr : array-like
        Input numeric array.
    conversion : {'none', 'kelvin_to_celsius'}
        Conversion mode.

    Returns
    -------
    numpy.ndarray
        Converted array (Kelvin � Celsius if selected), else unchanged.
    """
    if conversion == "kelvin_to_celsius":
        return arr - 273.15
    return arr


def choose_inputs():
    """
    Discover input Zarr stores using primary and fallback glob patterns.

    Returns
    -------
    list of str
        Sorted list of directory paths to Zarr inputs.

    Raises
    ------
    FileNotFoundError
        If neither primary nor fallback patterns produce any directories.
    """
    # Primary pattern
    paths = sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_PRIMARY)))
    if paths:
        return paths
    # Fallback pattern
    paths = sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_FALLBACK)))
    # Keep directories only
    paths = [p for p in paths if os.path.isdir(p)]
    if paths:
        return paths
    raise FileNotFoundError(
        f"No Zarr inputs found.\n"
        f"Tried: {os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_PRIMARY)} and {os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_FALLBACK)}.\n"
        f"Place your FCN3 .zarr in '{DEFAULT_INPUT_DIR}' or adjust DEFAULT_INPUT_DIR."
    )


def render_one_zarr(input_zarr: str, variable: str):
    """
    Render one Zarr dataset for a single variable into JPEG tiles and configuration.

    Parameters
    ----------
    input_zarr : str
        Path to a Zarr store.
    variable : str
        Data variable to render (e.g., 't2m', 'mslp', 'u10m', 'v10m').

    Side Effects
    ------------
    - Creates an output directory under `OUTPUT_ROOT/variable/zarr_leaf/base_leaf/`.
    - Writes one RGB JPEG and one alpha JPEG per valid time step.
    - Emits `0000-config.json` capturing bounds, sources, units, vmin/vmax, etc.

    Raises
    ------
    ValueError
        If the variable is not found, or if the rendered slice is not 2D.
    """
    print(f"\n[INFO] Loading FCN3 Zarr: {input_zarr}")
    ds = open_zarr_any(input_zarr)

    if variable not in ds.data_vars:
        raise ValueError(f"Variable '{variable}' not found in {input_zarr}. Available: {list(ds.data_vars)}")

    var = ds[variable]

    # Optional vertical level selection
    lev_dim = detect_level_dim(var)
    if lev_dim and LEVEL is not None:
        lev_vals = var[lev_dim].values
        idx = int(np.argmin(np.abs(lev_vals - float(LEVEL))))
        sel_level_val = lev_vals[idx]
        print(f"[INFO] Selecting {lev_dim}={sel_level_val}")
        var = var.sel({lev_dim: sel_level_val})
    elif lev_dim and LEVEL is None:
        print(f"[WARN] '{variable}' has vertical dim '{lev_dim}'. Using the first level. "
              f"To change, set LEVEL in CONFIG.")
        var = var.isel({lev_dim: 0})

    # Discover time + lead time
    t_name, lt_name = guess_time_coords(ds)
    base_time = parse_base_time(ds, t_name)
    print(f"[INFO] Base time ({t_name}): {base_time.isoformat()}")

    # Limit to a single initialization if var carries time dim
    if t_name in var.dims:
        var = var.isel({t_name: TIME_INDEX})

    # Decide normalization bounds on the chosen init
    range_source = var
    tmp_vals = apply_unit_conversion(range_source.values, UNIT_CONVERSION)

    if VMODE == "fixed":
        vmin, vmax = VMIN, VMAX
        print(f"[INFO] Using FIXED vmin/vmax: {vmin}, {vmax}")
    elif VMODE == "percentile":
        vmin = float(np.nanpercentile(tmp_vals, PMIN))
        vmax = float(np.nanpercentile(tmp_vals, PMAX))
        print(f"[INFO] Using PERCENTILES pmin={PMIN}, pmax={PMAX} -> vmin={vmin:.3f}, vmax={vmax:.3f}")
    else:
        vmin = float(np.nanmin(tmp_vals))
        vmax = float(np.nanmax(tmp_vals))
        print(f"[INFO] Using AUTO global range -> vmin={vmin:.3f}, vmax={vmax:.3f}")

    # Output directory
    zarr_leaf = os.path.basename(input_zarr.rstrip("/")).replace(".zarr", "")
    base_leaf = f"{format_ts(base_time)}_{variable}" + (f"_{LEVEL}hPa" if lev_dim and LEVEL is not None else "")
    out_dir = os.path.join(OUTPUT_ROOT, variable, zarr_leaf, base_leaf)
    os.makedirs(out_dir, exist_ok=True)
    print(f"[INFO] Output directory: {out_dir}")

    # Bounds for e2cc config
    latlon_min, latlon_max = compute_bounds(ds)

    # Iterate forecast lead times
    lead_vals = ds.coords[lt_name].values
    sources, alpha_sources = {}, {}

    # Units metadata
    units = ds[variable].attrs.get("units", "")
    if UNIT_CONVERSION == "kelvin_to_celsius":
        units = "C"

    for i, lt in enumerate(lead_vals):
        # Compute valid time
        if isinstance(lt, np.timedelta64) or "timedelta64" in str(type(lt)):
            hours = pd.to_timedelta(lt).total_seconds() / 3600.0
        else:
            hours = float(np.asarray(lt))
        valid_time = base_time + timedelta(hours=hours)

        # Extract slice
        if lt_name in var.dims:
            slice_da = var.isel({lt_name: i})
        else:
            slice_da = var  # if var only has spatial dims

        data = apply_unit_conversion(slice_da.values, UNIT_CONVERSION)

        # Normalize and convert to images
        norm01, _, _ = normalize_data(data, vmin, vmax)
        gray = to_grayscale_u8(norm01)
        alpha = alpha_from_nan(data, ALPHA_VALUE)

        if gray.ndim != 2:
            raise ValueError(f"Expected 2D field; got shape {gray.shape}. "
                             f"Check variable/LEVEL/TIME_INDEX for {variable}.")

        # Filenames (JPEG only)
        stamp = format_ts(valid_time)
        rgb_fn = f"{stamp}_rgb.jpeg"
        alpha_fn = f"{stamp}_alpha.jpeg"

        # Save RGB (3channel)
        rgb_pil = Image.fromarray(gray, mode="L").convert("RGB")
        rgb_pil.save(
            os.path.join(out_dir, rgb_fn),
            "JPEG",
            quality=JPEG_QUALITY,
            subsampling=JPEG_SUBSAMPLING,
            optimize=JPEG_OPTIMIZE,
        )

        # Save alpha (grayscale JPEG). E2CC requires JPEGno PNGs.
        alpha_pil = Image.fromarray(alpha, mode="L")
        alpha_pil.save(
            os.path.join(out_dir, alpha_fn),
            "JPEG",
            quality=JPEG_QUALITY,
            subsampling=JPEG_SUBSAMPLING,
            optimize=JPEG_OPTIMIZE,
        )

        key = format_key(valid_time)
        sources[key] = f"./{rgb_fn}"
        alpha_sources[key] = f"./{alpha_fn}"

        print(f"[OK] {variable}: {rgb_fn}  {alpha_fn}")

    # Remapping metadata (viewer-side colorization)
    remapping = {
        "input_min": 0.0,
        "input_max": 1.0,
        "output_min": 0.0,
        "output_max": 1.0,
        "output_gamma": 0.75
    }

    config = {
        "features": [{
            "name": f"FCN3 - {variable}" + (f" @ {LEVEL} hPa" if LEVEL is not None else ""),
            "type": "Image",
            "projection": "latlong",
            "sources": sources,
            "alpha_sources": alpha_sources,
            "latlon_min": latlon_min,
            "latlon_max": latlon_max,
            "remapping": remapping,
            "colormap": COLORMAP,
            "metadata": {
                "base_time": base_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "variable": variable,
                "units": units,
                "vmin": vmin,
                "vmax": vmax
            }
        }]
    }

    with open(os.path.join(out_dir, "0000-config.json"), "w") as f:
        json.dump(config, f, indent=2)

    print(f"[DONE] {variable}: wrote {os.path.join(out_dir, '0000-config.json')}")

    ds.close()


def main():
    """
    Entry point: discover inputs, render all requested variables for each Zarr.

    Workflow
    --------
    1. Ensure `OUTPUT_ROOT` exists.
    2. Discover inputs using primary and fallback patterns.
    3. For each input Zarr, iterate `VARIABLES` and call `render_one_zarr`.
    4. Print a completion message.

    Raises
    ------
    FileNotFoundError
        If no Zarr input directories are found under `DEFAULT_INPUT_DIR`.
    """
    os.makedirs(OUTPUT_ROOT, exist_ok=True)

    # Discover inputs
    inputs = sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_PRIMARY)))
    if not inputs:
        inputs = sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, DEFAULT_PATTERN_FALLBACK)))
        inputs = [p for p in inputs if os.path.isdir(p)]
    if not inputs:
        raise FileNotFoundError("No .zarr inputs found under DEFAULT_INPUT_DIR.")

    print("[INFO] Found inputs:")
    for p in inputs:
        print("   ", p)

    for p in inputs:
        for var in VARIABLES:
            render_one_zarr(p, var)

    print("\n[ALL DONE] Open the generated folder(s) in e2cc.")


if __name__ == "__main__":
    main()