# """Stormcast Weather API
#
# This module exposes a FastAPI application that serves forecast grids and point time
# series derived from local Zarr datasets for the Stormcast/FcN3 models.
#
# Notes
# -----
# - Endpoints provide: availability, time series at (lat, lon), all/specific-hour grids.
# - Supports geographic coordinates (`lat`, `lon`) or HRRR projected axes (`hrrr_x`, `hrrr_y`).
# - Applies GZip compression, CORS, and ETag/Cache-Control headers.
# """
#
# import os
# import re
# import hashlib
# from pathlib import Path
# from glob import glob
# from typing import Literal, Optional, List, Dict, Tuple
#
# import numpy as np
# import tensorstore as ts
# from pyproj import Proj
#
# from fastapi import FastAPI, Response, Request
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.middleware.gzip import GZipMiddleware
# from fastapi.responses import JSONResponse
#
# from config import BASE_DATA_DIR, RUN_FOLDER, ALLOWED_ORIGINS, HRRR_PROJ_STRING
#
# app = FastAPI(title="Stormcast Weather API")
#
# app.add_middleware(GZipMiddleware, minimum_size=1000)
#
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=ALLOWED_ORIGINS,
#     allow_credentials=True,
#     allow_methods=["GET"],
#     allow_headers=["*"],
# )
#
#
# class CustomError(Exception):
#     """
#     Application-specific exception that maps to a JSON error response.
#
#     Parameters
#     ----------
#     status_code : int
#         HTTP status code to return.
#     error : str
#         Short, machine-friendly error type/message.
#     details : str, optional
#         Optional human-readable details about the error.
#     """
#
#     def __init__(self, status_code: int, error: str, details: str = None):
#         self.status_code = status_code
#         self.error = error
#         self.details = details
#
#
# @app.exception_handler(CustomError)
# async def custom_error_handler(request: Request, exc: CustomError):
#     """
#     FastAPI exception handler for `CustomError`.
#
#     Parameters
#     ----------
#     request : fastapi.Request
#         Incoming HTTP request.
#     exc : CustomError
#         Raised custom error.
#
#     Returns
#     -------
#     fastapi.responses.JSONResponse
#         JSON payload with keys `error` and optional `details`, with the corresponding
#         HTTP status code.
#     """
#     content = {"error": exc.error}
#     if exc.details:
#         content["details"] = exc.details
#     return JSONResponse(status_code=exc.status_code, content=content)
#
#
# DATE_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#
#
# DATE_FOLDER_CACHE: Dict[str, Path] = {}
#
#
# def find_date_folder_path(date: str) -> Path:
#     """
#     Resolve the filesystem path to `<date>_24h` within a Stormcast data tree.
#
#     The function looks under `BASE_DATA_DIR` for a directory whose name contains
#     the substring "stormcast" (case-insensitive). Within that directory, it expects
#     `RUN_FOLDER/<date>_24h`.
#
#     Parameters
#     ----------
#     date : str
#         Target date in `YYYY-MM-DD` format.
#
#     Returns
#     -------
#     pathlib.Path
#         Path pointing to the `<date>_24h` directory.
#
#     Raises
#     ------
#     CustomError
#         500 if `BASE_DATA_DIR` does not exist.
#         404 if no matching date directory is found.
#     """
#     date_folder_name = f"{date}_24h"
#
#     if date in DATE_FOLDER_CACHE:
#         cached_path = DATE_FOLDER_CACHE[date]
#         if cached_path.exists():
#             return cached_path
#         else:
#             del DATE_FOLDER_CACHE[date]
#
#     base_dir = Path(BASE_DATA_DIR)
#
#     if not base_dir.exists():
#         raise CustomError(500, "Server Configuration Error", f"Base directory {BASE_DATA_DIR} does not exist.")
#
#     for folder in base_dir.iterdir():
#         if folder.is_dir() and "stormcast" in folder.name.lower():
#             target_date_path = folder / RUN_FOLDER / date_folder_name
#
#             if target_date_path.exists():
#                 DATE_FOLDER_CACHE[date] = target_date_path
#                 return target_date_path
#
#     raise CustomError(404, "Data not found", f"No stormcast data found for date: {date}")
#
#
# def resolve_zarr_path(model: str, date: str, ensemble_id: int) -> Path:
#     """
#     Return the Zarr store path for the given model/date/ensemble.
#
#     Parameters
#     ----------
#     model : str
#         One of {"stormcast", "fcn3"} (case-insensitive).
#     date : str
#         Date string in `YYYY-MM-DD` format.
#     ensemble_id : int
#         Non-negative ensemble identifier (0, 1, 2, ...).
#
#     Returns
#     -------
#     pathlib.Path
#         Filesystem path to `<date>_24h/{model}_member_{ensemble_id}.zarr`.
#
#     Raises
#     ------
#     CustomError
#         400 for invalid model/date/ensemble_id.
#         404/500 from `find_date_folder_path` if the date tree cannot be resolved.
#     """
#     model = model.lower()
#
#     if model not in ("stormcast", "fcn3"):
#         raise CustomError(400, "Invalid parameters", f"Unknown model: {model}")
#
#     if not DATE_FOLDER_RE.match(date):
#         raise CustomError(400, "Invalid parameters", "date must be in YYYY-MM-DD format")
#
#     if ensemble_id < 0:
#         raise CustomError(400, "Invalid parameters", "ensemble_id must be a non-negative integer")
#
#     date_dir = find_date_folder_path(date)
#     zarr_dir = date_dir / f"{model}_member_{ensemble_id}.zarr"
#
#     return zarr_dir
#
#
# def list_available_ensembles(model: str, date: str) -> List[int]:
#     """
#     List ensemble IDs available for a given model and date.
#
#     Parameters
#     ----------
#     model : str
#         Model identifier ("stormcast" or "fcn3").
#     date : str
#         Date string in `YYYY-MM-DD` format.
#
#     Returns
#     -------
#     list of int
#         Sorted list of unique ensemble IDs (e.g., [0, 1, 2]). Empty list if
#         the date path cannot be resolved (or on error).
#     """
#     model = model.lower()
#
#     try:
#         date_dir = find_date_folder_path(date)
#     except CustomError:
#         return []
#
#     pattern = str(date_dir / f"{model}_member_*.zarr")
#
#     ids: List[int] = []
#     for p in glob(pattern):
#         m = re.search(r"_member_(\d+)\.zarr$", p)
#         if m:
#             ids.append(int(m.group(1)))
#     return sorted(set(ids))
#
#
# def list_available_variables(zarr_path: Path) -> List[str]:
#     """
#     List variable folder names inside a Zarr store, excluding coordinate arrays.
#
#     Parameters
#     ----------
#     zarr_path : pathlib.Path
#         Filesystem path to a Zarr store.
#
#     Returns
#     -------
#     list of str
#         Sorted list of variable names (folders), excluding {"lat", "lon", "hrrr_x", "hrrr_y"}.
#         Returns empty list if the store path does not exist.
#     """
#     if not zarr_path.exists():
#         return []
#
#     ignore = {"lat", "lon", "hrrr_x", "hrrr_y"}
#     vars_ = []
#     for child in zarr_path.iterdir():
#         if child.is_dir():
#             name = child.name
#             if name not in ignore:
#                 vars_.append(name)
#     return sorted(vars_)
#
#
# async def read_zarr_array(zarr_path: str, folder_name: str) -> np.ndarray:
#     """
#     Read and return a squeezed NumPy array from a subfolder in a Zarr store.
#
#     The function first attempts to open with the Zarr v3 driver and falls back to
#     the v2 driver for backward compatibility.
#
#     Parameters
#     ----------
#     zarr_path : str
#         Filesystem path to the Zarr store (directory).
#     folder_name : str
#         Variable (or coordinate) subfolder name to read.
#
#     Returns
#     -------
#     numpy.ndarray
#         Array with singleton dimensions removed (via `np.squeeze`).
#
#     Raises
#     ------
#     FileNotFoundError
#         If the requested subfolder does not exist.
#     Exception
#         Any tensorstore error will propagate after v2 fallback fails.
#     """
#     path = os.path.join(zarr_path, folder_name)
#     if not os.path.exists(path):
#         raise FileNotFoundError(f"Folder '{folder_name}' not found at {path}")
#
#     try:
#         dataset = await ts.open({
#             "driver": "zarr3",
#             "kvstore": {"driver": "file", "path": path}
#         })
#     except Exception:
#         dataset = await ts.open({
#             "driver": "zarr",
#             "kvstore": {"driver": "file", "path": path}
#         })
#
#     data = await dataset.read()
#     return np.squeeze(data)
#
#
# async def fetch_base_data(model: str, date: str, variable: str, ensemble_id: int):
#     """
#     Fetch a variable array and any available coordinate vectors from a Zarr store.
#
#     This convenience function resolves the Zarr path, reads the requested variable,
#     and attempts to load coordinate arrays: `lat`, `lon`, `hrrr_x`, `hrrr_y`.
#
#     Parameters
#     ----------
#     model : str
#         Model identifier ("stormcast" or "fcn3").
#     date : str
#         Date string in `YYYY-MM-DD` format.
#     variable : str
#         Zarr subfolder to read (e.g., "precip", "t2m").
#     ensemble_id : int
#         Non-negative ensemble identifier.
#
#     Returns
#     -------
#     tuple
#         `(raw_data, coords)` where:
#         - `raw_data` : numpy.ndarray
#             Numeric array, NaNs replaced by 0, rounded to 2 decimals.
#         - `coords` : dict
#             May include any of {"lat","lon","hrrr_x","hrrr_y"} mapped to lists (rounded 2 decimals).
#
#     Raises
#     ------
#     CustomError
#         503 if the Zarr store does not exist.
#         404 if the variable subfolder is missing.
#         500 for generic read/processing failures.
#     """
#     zarr_path = resolve_zarr_path(model, date, ensemble_id)
#
#     if not zarr_path.exists():
#         raise CustomError(503, "Model run not available", f"Missing: {str(zarr_path)}")
#
#     try:
#         raw_data = await read_zarr_array(str(zarr_path), variable)
#     except FileNotFoundError:
#         raise CustomError(404, "Resource not found", "Invalid variable or ensemble_id not available")
#     except Exception as e:
#         raise CustomError(500, "Internal Server Error", f"Failed to process data arrays: {e}")
#
#     coords: Dict[str, List[float]] = {}
#     for coord_name in ["lat", "lon", "hrrr_x", "hrrr_y"]:
#         try:
#             arr = await read_zarr_array(str(zarr_path), coord_name)
#             if arr.ndim > 1 and coord_name in ["lat", "lon"]:
#                 arr = arr[:, 0] if coord_name == "lat" else arr[0, :]
#             coords[coord_name] = np.round(arr, 2).tolist()
#         except FileNotFoundError:
#             pass
#
#     raw_data = np.nan_to_num(raw_data, nan=0.0)
#     raw_data = np.round(raw_data, decimals=2)
#
#     return raw_data, coords
#
#
# def generate_etag(ident_string: str) -> str:
#     """
#     Generate a weak ETag hash for cache validation.
#
#     Parameters
#     ----------
#     ident_string : str
#         Deterministic string that identifies a unique response payload.
#
#     Returns
#     -------
#     str
#         MD5 hex digest string suitable for use in a weak ETag header.
#     """
#     return hashlib.md5(ident_string.encode()).hexdigest()
#
#
# def get_1d_lat_lon(coords: dict):
#     """
#     Derive 1D latitude and longitude axes from available coordinates.
#
#     Behavior
#     --------
#     - If `hrrr_x` and `hrrr_y` exist, compute 1D lat/lon axes using the HRRR
#       projection with midline sampling (convert each axis while fixing the other at
#       its midpoint).
#     - Otherwise, returns `coords.get("lat", [])` and `coords.get("lon", [])`.
#
#     Parameters
#     ----------
#     coords : dict
#         Dictionary potentially containing "lat", "lon", "hrrr_x", "hrrr_y" lists.
#
#     Returns
#     -------
#     tuple of list
#         (lat_1d, lon_1d), rounded to 2 decimals.
#     """
#     if "hrrr_x" in coords and "hrrr_y" in coords:
#         hrrr_proj = Proj(HRRR_PROJ_STRING)
#
#         x_arr = np.array(coords["hrrr_x"])
#         y_arr = np.array(coords["hrrr_y"])
#
#         mid_y = y_arr[len(y_arr) // 2] if len(y_arr) > 0 else 0
#         mid_x = x_arr[len(x_arr) // 2] if len(x_arr) > 0 else 0
#
#         lons, _ = hrrr_proj(x_arr, np.full_like(x_arr, mid_y), inverse=True)
#         _, lats = hrrr_proj(np.full_like(y_arr, mid_x), y_arr, inverse=True)
#
#         return np.round(lats, 2).tolist(), np.round(lons, 2).tolist()
#
#     return coords.get("lat", []), coords.get("lon", [])
#
#
# def nearest_neighbor_lookup(data_3d, y_array, x_array, target_y, target_x):
#     """
#     Return raw grid-cell values using nearest-neighbor lookup.
#
#     This helper is a simple replacement for bilinear interpolation when you want the
#     exact grid point closest to (target_y, target_x).
#
#     Parameters
#     ----------
#     data_3d : numpy.ndarray
#         Array to index (either 2D (y, x) or 3D (time, y, x)).
#     y_array : array-like
#         1D array-like of y coordinates.
#     x_array : array-like
#         1D array-like of x coordinates.
#     target_y : float
#         Target y coordinate (same units as y_array).
#     target_x : float
#         Target x coordinate (same units as x_array).
#
#     Returns
#     -------
#     list of float
#         Values at the nearest grid point (length `time` if data_3d is 3D; length 1 if 2D),
#         rounded to 2 decimals.
#     """
#     y_arr = np.array(y_array)
#     x_arr = np.array(x_array)
#
#     y_idx = np.abs(y_arr - target_y).argmin()
#     x_idx = np.abs(x_arr - target_x).argmin()
#
#     if data_3d.ndim >= 3:
#         raw_values = data_3d[:, y_idx, x_idx]
#     else:
#         raw_values = data_3d[y_idx, x_idx]
#
#     if np.isscalar(raw_values):
#         return [round(float(raw_values), 2)]
#     return np.round(raw_values, 2).tolist()
#
#
# @app.get("/api/{model}/{date}/available")
# async def available(model: Literal["stormcast", "fcn3"], date: str, ensemble_probe: int = 0):
#     """
#     List available ensembles and variables for a given model/date.
#
#     Parameters
#     ----------
#     model : {'stormcast', 'fcn3'}
#         Model identifier.
#     date : str
#         Date string in `YYYY-MM-DD` format.
#     ensemble_probe : int, optional
#         If present in the available list, variables are probed from that ensemble;
#         otherwise falls back to the first available ensemble (if any). Default is 0.
#
#     Returns
#     -------
#     dict
#         {
#             "model": str,
#             "date": str,
#             "run_folder": str,
#             "available_ensembles": list of int,
#             "variables_probe_ensemble": int or None,
#             "available_variables": list of str
#         }
#     """
#     ens = list_available_ensembles(model, date)
#     variables: List[str] = []
#
#     probe_id = ensemble_probe if ensemble_probe in ens else (ens[0] if ens else None)
#     if probe_id is not None:
#         zarr_path = resolve_zarr_path(model, date, probe_id)
#         variables = list_available_variables(zarr_path)
#
#     return {
#         "model": model,
#         "date": date,
#         "run_folder": RUN_FOLDER,
#         "available_ensembles": ens,
#         "variables_probe_ensemble": probe_id,
#         "available_variables": variables
#     }
#
#
# @app.get("/api/{model}/{date}/{variable}/timeseries")
# async def get_timeseries(
#         model: Literal["stormcast", "fcn3"],
#         date: str,
#         variable: str,
#         lat: float,
#         lon: float,
#         ensemble_id: int = 0,
#         preview: bool = False,
#         response: Response = None,
# ):
#     """
#     Return a time series at the nearest grid point to (lat, lon).
#
#     The nearest grid point is chosen using either HRRR projected axes (if
#     available) or geographic lat/lon (2D min distance or 1D nearest).
#
#     Parameters
#     ----------
#     model : {'stormcast', 'fcn3'}
#         Model identifier.
#     date : str
#         Date string in `YYYY-MM-DD` format.
#     variable : str
#         Variable subfolder in the Zarr store.
#     lat : float
#         Latitude in degrees.
#     lon : float
#         Longitude in degrees.
#     ensemble_id : int, optional
#         Ensemble member to read (default = 0).
#     preview : bool, optional
#         If True, returns fewer points (first 5 timesteps) for quick inspection.
#     response : fastapi.Response, optional
#         Response object (used to set headers).
#
#     Returns
#     -------
#     dict
#         {
#             "date": str,
#             "variable": str,
#             "model": str,
#             "ensemble_id": int,
#             "lat": float,
#             "lon": float,
#             "lead_time": list of int,
#             "values": list of float
#         }
#
#     Raises
#     ------
#     CustomError
#         404 if variable missing, 500 if no coordinates, 503 if run missing.
#     """
#     if response is None:
#         response = Response()
#
#     zarr_path = resolve_zarr_path(model, date, ensemble_id)
#
#     if not zarr_path.exists():
#         raise CustomError(503, "Model run not available", f"Missing: {str(zarr_path)}")
#
#
#     try:
#         raw_data = await read_zarr_array(str(zarr_path), variable)
#     except FileNotFoundError:
#         raise CustomError(404, "Resource not found", f"Variable '{variable}' not found in zarr.")
#
#     lat_arr, lon_arr = None, None
#     hrrr_x, hrrr_y = None, None
#
#     try:
#         lat_arr = await read_zarr_array(str(zarr_path), "lat")
#         lon_arr = await read_zarr_array(str(zarr_path), "lon")
#     except FileNotFoundError:
#         pass
#
#     try:
#         hrrr_x = await read_zarr_array(str(zarr_path), "hrrr_x")
#         hrrr_y = await read_zarr_array(str(zarr_path), "hrrr_y")
#     except FileNotFoundError:
#         pass
#
#     if lat_arr is None and hrrr_x is None:
#         raise CustomError(500, "Internal Server Error", "No coordinate variables found in Zarr file.")
#
#     y_idx, x_idx = 0, 0
#
#     if hrrr_x is not None and hrrr_y is not None and hrrr_x.ndim == 1:
#
#         hrrr_proj = Proj(HRRR_PROJ_STRING)
#         target_x, target_y = hrrr_proj(lon, lat)
#
#         y_idx = np.abs(hrrr_y - target_y).argmin()
#         x_idx = np.abs(hrrr_x - target_x).argmin()
#
#     elif lat_arr is not None and lon_arr is not None:
#
#         if lat_arr.ndim >= 2 and lon_arr.ndim >= 2:
#             dist_sq = (lat_arr - lat)**2 + (lon_arr - lon)**2
#             y_idx, x_idx = np.unravel_index(np.argmin(dist_sq), lat_arr.shape)
#         else:
#
#             y_idx = np.abs(lat_arr - lat).argmin()
#             x_idx = np.abs(lon_arr - lon).argmin()
#
#     raw_data = np.nan_to_num(raw_data, nan=0.0)
#     max_hours = min(25, raw_data.shape[0] if raw_data.ndim >= 3 else 1)
#
#
#     if raw_data.ndim >= 3:
#         timeseries_values = raw_data[:max_hours, y_idx, x_idx]
#     else:
#         timeseries_values = np.array([raw_data[y_idx, x_idx]])
#
#     timeseries_values = np.round(timeseries_values, 2).tolist()
#     lead_times = list(range(len(timeseries_values)))
#
#     if preview:
#         timeseries_values = timeseries_values[:5]
#         lead_times = lead_times[:5]
#
#     payload = {
#         "date": date,
#         "variable": variable,
#         "model": model,
#         "ensemble_id": ensemble_id,
#         "lat": lat,
#         "lon": lon,
#         "lead_time": lead_times,
#         "values": timeseries_values
#     }
#
#     response.headers["Cache-Control"] = "public, max-age=3600"
#     response.headers["ETag"] = f'W/"{generate_etag(f"ts-{model}-{date}-{variable}-{lat}-{lon}-{ensemble_id}")}"'
#     return payload
#
#
# @app.get("/api/{model}/{date}/{variable}/{hours}")
# async def get_specific_hours(
#         model: Literal["stormcast", "fcn3"],
#         date: str,
#         variable: str,
#         hours: str,
#         ensemble_id: int = 0,
#         preview: bool = False,
#         response: Response = None,
# ):
#     """
#     Return flattened grid values for specific lead hours.
#
#     If the data is 3D (time, y, x), selection is made along `time` using `hours`.
#     If 2D (y, x), the entire slice is returned and wrapped as a single time step.
#
#     Parameters
#     ----------
#     model : {'stormcast', 'fcn3'}
#         Model identifier.
#     date : str
#         Date string in `YYYY-MM-DD` format.
#     variable : str
#         Variable subfolder in the Zarr store.
#     hours : str
#         Comma-separated list of integers (e.g., "0,1,6,12").
#     ensemble_id : int, optional
#         Ensemble member to read (default = 0).
#     preview : bool, optional
#         If True, returns small subarrays for quick inspection.
#     response : fastapi.Response, optional
#         Response object (used to set headers).
#
#     Returns
#     -------
#     dict
#         {
#             "date": str,
#             "variable": str,
#             "model": str,
#             "ensemble_id": int,
#             "lead_time": list of int,
#             "lat": list of float,
#             "lon": list of float,
#             "values": list of float  # flattened
#         }
#
#     Raises
#     ------
#     CustomError
#         400 for invalid `hours` format.
#         404 for hour out-of-bounds.
#         503 if the run is missing.
#     """
#     if response is None:
#         response = Response()
#
#     try:
#         hour_list = [int(h.strip()) for h in hours.split(",")]
#     except ValueError:
#         raise CustomError(
#             400,
#             "Invalid parameters",
#             "Hours must be an integer or comma-separated integers (e.g., '1' or '1,2,3')"
#         )
#
#     raw_data, coords = await fetch_base_data(model, date, variable, ensemble_id)
#     lat_1d, lon_1d = get_1d_lat_lon(coords)
#
#     max_valid_hour = raw_data.shape[0] - 1 if raw_data.ndim >= 3 else 0
#     for h in hour_list:
#         if h < 0 or h > 24 or h > max_valid_hour:
#             raise CustomError(404, "Resource not found", f"Hour {h} is out of bounds")
#
#     if raw_data.ndim >= 3:
#         data_slice = raw_data[hour_list, :, :]
#     else:
#         data_slice = np.array([raw_data])
#
#     if preview:
#         lat_1d = lat_1d[:10]
#         lon_1d = lon_1d[:10]
#         if data_slice.ndim >= 3:
#             data_slice = data_slice[:, :10, :10]
#         else:
#             data_slice = data_slice[:10, :10]
#
#     flat_values = data_slice.flatten().tolist()
#
#     payload = {
#         "date": date,
#         "variable": variable,
#         "model": model,
#         "ensemble_id": ensemble_id,
#         "lead_time": hour_list,
#         "lat": lat_1d,
#         "lon": lon_1d,
#         "values": flat_values
#     }
#
#     response.headers["Cache-Control"] = "public, max-age=3600"
#     response.headers["ETag"] = f'W/"{generate_etag(f"sh-{model}-{date}-{variable}-{hours}-{ensemble_id}")}"'
#     return payload
#
#
# @app.get("/api/{model}/{date}/{variable}")
# async def get_all_hours(
#         model: Literal["stormcast", "fcn3"],
#         date: str,
#         variable: str,
#         ensemble_id: int = 0,
#         preview: bool = False,
#         response: Response = None,
# ):
#     """
#     Return flattened grid values for all available hours (up to 25).
#
#     If the data is 3D (time, y, x), this returns the first 25 hours (0..24) or fewer
#     if the array is shorter. If 2D, a single slice is returned.
#
#     Parameters
#     ----------
#     model : {'stormcast', 'fcn3'}
#         Model identifier.
#     date : str
#         Date string in `YYYY-MM-DD` format.
#     variable : str
#         Variable subfolder in the Zarr store.
#     ensemble_id : int, optional
#         Ensemble member to read (default = 0).
#     preview : bool, optional
#         If True, trims to small subarrays and the first 2 lead times.
#     response : fastapi.Response, optional
#         Response object (used to set headers).
#
#     Returns
#     -------
#     dict
#         {
#             "date": str,
#             "variable": str,
#             "model": str,
#             "ensemble_id": int,
#             "lead_time": list of int,
#             "lat": list of float,
#             "lon": list of float,
#             "values": list of float  # flattened
#         }
#     """
#     if response is None:
#         response = Response()
#
#     raw_data, coords = await fetch_base_data(model, date, variable, ensemble_id)
#     lat_1d, lon_1d = get_1d_lat_lon(coords)
#
#     max_hours = min(25, raw_data.shape[0] if raw_data.ndim >= 3 else 1)
#     data_slice = raw_data[:max_hours, :, :] if raw_data.ndim >= 3 else raw_data
#
#     lead_times = list(range(data_slice.shape[0] if data_slice.ndim >= 3 else 1))
#
#     if preview:
#         lat_1d = lat_1d[:10]
#         lon_1d = lon_1d[:10]
#         lead_times = lead_times[:2]
#         if data_slice.ndim >= 3:
#             data_slice = data_slice[:2, :10, :10]
#         else:
#             data_slice = data_slice[:10, :10]
#
#     flat_values = data_slice.flatten().tolist()
#
#     payload = {
#         "date": date,
#         "variable": variable,
#         "model": model,
#         "ensemble_id": ensemble_id,
#         "lead_time": lead_times,
#         "lat": lat_1d,
#         "lon": lon_1d,
#         "values": flat_values
#     }
#
#     response.headers["Cache-Control"] = "public, max-age=3600"
#     response.headers["ETag"] = f'W/"{generate_etag(f"all-{model}-{date}-{variable}-{ensemble_id}")}"'
#     return payload


"""Stormcast Weather API

This module exposes a FastAPI application that serves forecast grids and point time
series derived from local Zarr datasets for the Stormcast/FcN3 models.

Notes
-----
- Endpoints provide: availability, time series at (lat, lon), all/specific-hour grids.
- Supports geographic coordinates (`lat`, `lon`) or HRRR projected axes (`hrrr_x`, `hrrr_y`).
- Applies GZip compression, CORS, and ETag/Cache-Control headers.
"""

import os
import re
import hashlib
import logging
from pathlib import Path
from glob import glob
from typing import Literal, Optional, List, Dict, Tuple

import numpy as np
import tensorstore as ts
from pyproj import Proj

from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from config import BASE_DATA_DIR, RUN_FOLDER, ALLOWED_ORIGINS, HRRR_PROJ_STRING

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("stormcast_api")

app = FastAPI(title="Stormcast Weather API")

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


class CustomError(Exception):
    """
    Application-specific exception that maps to a JSON error response.
    """
    def __init__(self, status_code: int, error: str, details: str = None):
        self.status_code = status_code
        self.error = error
        self.details = details


@app.exception_handler(CustomError)
async def custom_error_handler(request: Request, exc: CustomError):
    """
    FastAPI exception handler for `CustomError`.
    """
    # Log the custom error so it's visible in the server console
    if exc.status_code >= 500:
        logger.error(f"Server Error {exc.status_code}: {exc.error} - {exc.details}")
    else:
        logger.warning(f"Client Error {exc.status_code}: {exc.error} - {exc.details}")

    content = {"error": exc.error}
    if exc.details:
        content["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=content)


DATE_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


DATE_FOLDER_CACHE: Dict[str, Path] = {}


def find_date_folder_path(date: str) -> Path:
    """
    Resolve the filesystem path to `<date>_24h` within a Stormcast data tree.
    """
    date_folder_name = f"{date}_24h"

    if date in DATE_FOLDER_CACHE:
        cached_path = DATE_FOLDER_CACHE[date]
        if cached_path.exists():
            logger.debug(f"Cache hit for date path: {date}")
            return cached_path
        else:
            logger.info(f"Cached path for {date} no longer exists. Removing from cache.")
            del DATE_FOLDER_CACHE[date]

    base_dir = Path(BASE_DATA_DIR)

    if not base_dir.exists():
        raise CustomError(500, "Server Configuration Error", f"Base directory {BASE_DATA_DIR} does not exist.")

    for folder in base_dir.iterdir():
        if folder.is_dir() and "stormcast" in folder.name.lower():
            target_date_path = folder / RUN_FOLDER / date_folder_name

            if target_date_path.exists():
                logger.info(f"Resolved new path for date {date}: {target_date_path}")
                DATE_FOLDER_CACHE[date] = target_date_path
                return target_date_path

    raise CustomError(404, "Data not found", f"No stormcast data found for date: {date}")


def resolve_zarr_path(model: str, date: str, ensemble_id: int) -> Path:
    """
    Return the Zarr store path for the given model/date/ensemble.
    """
    model = model.lower()

    if model not in ("stormcast", "fcn3"):
        raise CustomError(400, "Invalid parameters", f"Unknown model: {model}")

    if not DATE_FOLDER_RE.match(date):
        raise CustomError(400, "Invalid parameters", "date must be in YYYY-MM-DD format")

    if ensemble_id < 0:
        raise CustomError(400, "Invalid parameters", "ensemble_id must be a non-negative integer")

    date_dir = find_date_folder_path(date)
    zarr_dir = date_dir / f"{model}_member_{ensemble_id}.zarr"

    return zarr_dir


def list_available_ensembles(model: str, date: str) -> List[int]:
    """
    List ensemble IDs available for a given model and date.
    """
    model = model.lower()

    try:
        date_dir = find_date_folder_path(date)
    except CustomError:
        return []

    pattern = str(date_dir / f"{model}_member_*.zarr")

    ids: List[int] = []
    for p in glob(pattern):
        m = re.search(r"_member_(\d+)\.zarr$", p)
        if m:
            ids.append(int(m.group(1)))
    return sorted(set(ids))


def list_available_variables(zarr_path: Path) -> List[str]:
    """
    List variable folder names inside a Zarr store, excluding coordinate arrays.
    """
    if not zarr_path.exists():
        return []

    ignore = {"lat", "lon", "hrrr_x", "hrrr_y"}
    vars_ = []
    for child in zarr_path.iterdir():
        if child.is_dir():
            name = child.name
            if name not in ignore:
                vars_.append(name)
    return sorted(vars_)


async def read_zarr_array(zarr_path: str, folder_name: str) -> np.ndarray:
    """
    Read and return a squeezed NumPy array from a subfolder in a Zarr store.
    """
    path = os.path.join(zarr_path, folder_name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Folder '{folder_name}' not found at {path}")

    logger.debug(f"Reading Zarr array from: {path}")
    try:
        dataset = await ts.open({
            "driver": "zarr3",
            "kvstore": {"driver": "file", "path": path}
        })
    except Exception:
        logger.debug(f"zarr3 driver failed for {path}, falling back to zarr v2")
        dataset = await ts.open({
            "driver": "zarr",
            "kvstore": {"driver": "file", "path": path}
        })

    data = await dataset.read()
    return np.squeeze(data)


async def fetch_base_data(model: str, date: str, variable: str, ensemble_id: int):
    """
    Fetch a variable array and any available coordinate vectors from a Zarr store.
    """
    logger.info(f"Fetching base data: model={model}, date={date}, var={variable}, ens={ensemble_id}")
    zarr_path = resolve_zarr_path(model, date, ensemble_id)

    if not zarr_path.exists():
        raise CustomError(503, "Model run not available", f"Missing: {str(zarr_path)}")

    try:
        raw_data = await read_zarr_array(str(zarr_path), variable)
    except FileNotFoundError:
        raise CustomError(404, "Resource not found", "Invalid variable or ensemble_id not available")
    except Exception as e:
        logger.error(f"Failed to process data arrays at {zarr_path}: {e}")
        raise CustomError(500, "Internal Server Error", f"Failed to process data arrays: {e}")

    coords: Dict[str, List[float]] = {}
    for coord_name in ["lat", "lon", "hrrr_x", "hrrr_y"]:
        try:
            arr = await read_zarr_array(str(zarr_path), coord_name)
            if arr.ndim > 1 and coord_name in ["lat", "lon"]:
                arr = arr[:, 0] if coord_name == "lat" else arr[0, :]
            coords[coord_name] = np.round(arr, 2).tolist()
        except FileNotFoundError:
            pass

    raw_data = np.nan_to_num(raw_data, nan=0.0)
    raw_data = np.round(raw_data, decimals=2)

    return raw_data, coords


def generate_etag(ident_string: str) -> str:
    """Generate a weak ETag hash for cache validation."""
    return hashlib.md5(ident_string.encode()).hexdigest()


def get_1d_lat_lon(coords: dict):
    """Derive 1D latitude and longitude axes from available coordinates."""
    if "hrrr_x" in coords and "hrrr_y" in coords:
        hrrr_proj = Proj(HRRR_PROJ_STRING)

        x_arr = np.array(coords["hrrr_x"])
        y_arr = np.array(coords["hrrr_y"])

        mid_y = y_arr[len(y_arr) // 2] if len(y_arr) > 0 else 0
        mid_x = x_arr[len(x_arr) // 2] if len(x_arr) > 0 else 0

        lons, _ = hrrr_proj(x_arr, np.full_like(x_arr, mid_y), inverse=True)
        _, lats = hrrr_proj(np.full_like(y_arr, mid_x), y_arr, inverse=True)

        return np.round(lats, 2).tolist(), np.round(lons, 2).tolist()

    return coords.get("lat", []), coords.get("lon", [])


def nearest_neighbor_lookup(data_3d, y_array, x_array, target_y, target_x):
    """Return raw grid-cell values using nearest-neighbor lookup."""
    y_arr = np.array(y_array)
    x_arr = np.array(x_array)

    y_idx = np.abs(y_arr - target_y).argmin()
    x_idx = np.abs(x_arr - target_x).argmin()

    if data_3d.ndim >= 3:
        raw_values = data_3d[:, y_idx, x_idx]
    else:
        raw_values = data_3d[y_idx, x_idx]

    if np.isscalar(raw_values):
        return [round(float(raw_values), 2)]
    return np.round(raw_values, 2).tolist()


@app.get("/api/{model}/{date}/available")
async def available(model: Literal["stormcast", "fcn3"], date: str, ensemble_probe: int = 0):
    """List available ensembles and variables for a given model/date."""
    logger.info(f"Availability requested for model={model}, date={date}")
    ens = list_available_ensembles(model, date)
    variables: List[str] = []

    probe_id = ensemble_probe if ensemble_probe in ens else (ens[0] if ens else None)
    if probe_id is not None:
        zarr_path = resolve_zarr_path(model, date, probe_id)
        variables = list_available_variables(zarr_path)

    return {
        "model": model,
        "date": date,
        "run_folder": RUN_FOLDER,
        "available_ensembles": ens,
        "variables_probe_ensemble": probe_id,
        "available_variables": variables
    }


@app.get("/api/{model}/{date}/{variable}/timeseries")
async def get_timeseries(
        model: Literal["stormcast", "fcn3"],
        date: str,
        variable: str,
        lat: float,
        lon: float,
        ensemble_id: int = 0,
        preview: bool = False,
        response: Response = None,
):
    """Return a time series at the nearest grid point to (lat, lon)."""
    logger.info(f"Timeseries requested: model={model}, date={date}, var={variable}, lat={lat}, lon={lon}")
    if response is None:
        response = Response()

    zarr_path = resolve_zarr_path(model, date, ensemble_id)

    if not zarr_path.exists():
        raise CustomError(503, "Model run not available", f"Missing: {str(zarr_path)}")

    try:
        raw_data = await read_zarr_array(str(zarr_path), variable)
    except FileNotFoundError:
        raise CustomError(404, "Resource not found", f"Variable '{variable}' not found in zarr.")

    lat_arr, lon_arr = None, None
    hrrr_x, hrrr_y = None, None

    try:
        lat_arr = await read_zarr_array(str(zarr_path), "lat")
        lon_arr = await read_zarr_array(str(zarr_path), "lon")
    except FileNotFoundError:
        pass

    try:
        hrrr_x = await read_zarr_array(str(zarr_path), "hrrr_x")
        hrrr_y = await read_zarr_array(str(zarr_path), "hrrr_y")
    except FileNotFoundError:
        pass

    if lat_arr is None and hrrr_x is None:
        raise CustomError(500, "Internal Server Error", "No coordinate variables found in Zarr file.")

    y_idx, x_idx = 0, 0

    if hrrr_x is not None and hrrr_y is not None and hrrr_x.ndim == 1:
        hrrr_proj = Proj(HRRR_PROJ_STRING)
        target_x, target_y = hrrr_proj(lon, lat)

        y_idx = np.abs(hrrr_y - target_y).argmin()
        x_idx = np.abs(hrrr_x - target_x).argmin()

    elif lat_arr is not None and lon_arr is not None:
        if lat_arr.ndim >= 2 and lon_arr.ndim >= 2:
            dist_sq = (lat_arr - lat)**2 + (lon_arr - lon)**2
            y_idx, x_idx = np.unravel_index(np.argmin(dist_sq), lat_arr.shape)
        else:
            y_idx = np.abs(lat_arr - lat).argmin()
            x_idx = np.abs(lon_arr - lon).argmin()

    raw_data = np.nan_to_num(raw_data, nan=0.0)
    max_hours = min(25, raw_data.shape[0] if raw_data.ndim >= 3 else 1)

    if raw_data.ndim >= 3:
        timeseries_values = raw_data[:max_hours, y_idx, x_idx]
    else:
        timeseries_values = np.array([raw_data[y_idx, x_idx]])

    timeseries_values = np.round(timeseries_values, 2).tolist()
    lead_times = list(range(len(timeseries_values)))

    if preview:
        timeseries_values = timeseries_values[:5]
        lead_times = lead_times[:5]

    payload = {
        "date": date,
        "variable": variable,
        "model": model,
        "ensemble_id": ensemble_id,
        "lat": lat,
        "lon": lon,
        "lead_time": lead_times,
        "values": timeseries_values
    }

    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["ETag"] = f'W/"{generate_etag(f"ts-{model}-{date}-{variable}-{lat}-{lon}-{ensemble_id}")}"'
    return payload


@app.get("/api/{model}/{date}/{variable}/{hours}")
async def get_specific_hours(
        model: Literal["stormcast", "fcn3"],
        date: str,
        variable: str,
        hours: str,
        ensemble_id: int = 0,
        preview: bool = False,
        response: Response = None,
):
    """Return flattened grid values for specific lead hours."""
    logger.info(f"Specific hours grid requested: model={model}, date={date}, var={variable}, hours={hours}")
    if response is None:
        response = Response()

    try:
        hour_list = [int(h.strip()) for h in hours.split(",")]
    except ValueError:
        raise CustomError(
            400,
            "Invalid parameters",
            "Hours must be an integer or comma-separated integers (e.g., '1' or '1,2,3')"
        )

    raw_data, coords = await fetch_base_data(model, date, variable, ensemble_id)
    lat_1d, lon_1d = get_1d_lat_lon(coords)

    max_valid_hour = raw_data.shape[0] - 1 if raw_data.ndim >= 3 else 0
    for h in hour_list:
        if h < 0 or h > 24 or h > max_valid_hour:
            raise CustomError(404, "Resource not found", f"Hour {h} is out of bounds")

    if raw_data.ndim >= 3:
        data_slice = raw_data[hour_list, :, :]
    else:
        data_slice = np.array([raw_data])

    if preview:
        lat_1d = lat_1d[:10]
        lon_1d = lon_1d[:10]
        if data_slice.ndim >= 3:
            data_slice = data_slice[:, :10, :10]
        else:
            data_slice = data_slice[:10, :10]

    flat_values = data_slice.flatten().tolist()

    payload = {
        "date": date,
        "variable": variable,
        "model": model,
        "ensemble_id": ensemble_id,
        "lead_time": hour_list,
        "lat": lat_1d,
        "lon": lon_1d,
        "values": flat_values
    }

    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["ETag"] = f'W/"{generate_etag(f"sh-{model}-{date}-{variable}-{hours}-{ensemble_id}")}"'
    return payload


@app.get("/api/{model}/{date}/{variable}")
async def get_all_hours(
        model: Literal["stormcast", "fcn3"],
        date: str,
        variable: str,
        ensemble_id: int = 0,
        preview: bool = False,
        response: Response = None,
):
    """Return flattened grid values for all available hours (up to 25)."""
    logger.info(f"All hours grid requested: model={model}, date={date}, var={variable}")
    if response is None:
        response = Response()

    raw_data, coords = await fetch_base_data(model, date, variable, ensemble_id)
    lat_1d, lon_1d = get_1d_lat_lon(coords)

    max_hours = min(25, raw_data.shape[0] if raw_data.ndim >= 3 else 1)
    data_slice = raw_data[:max_hours, :, :] if raw_data.ndim >= 3 else raw_data

    lead_times = list(range(data_slice.shape[0] if data_slice.ndim >= 3 else 1))

    if preview:
        lat_1d = lat_1d[:10]
        lon_1d = lon_1d[:10]
        lead_times = lead_times[:2]
        if data_slice.ndim >= 3:
            data_slice = data_slice[:2, :10, :10]
        else:
            data_slice = data_slice[:10, :10]

    flat_values = data_slice.flatten().tolist()

    payload = {
        "date": date,
        "variable": variable,
        "model": model,
        "ensemble_id": ensemble_id,
        "lead_time": lead_times,
        "lat": lat_1d,
        "lon": lon_1d,
        "values": flat_values
    }

    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["ETag"] = f'W/"{generate_etag(f"all-{model}-{date}-{variable}-{ensemble_id}")}"'
    return payload