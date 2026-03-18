
import yaml
from pathlib import Path


config_path = Path("config.yaml")
with open(config_path, "r") as f:
    config = yaml.safe_load(f)


BASE_DATA_DIR = config["paths"]["base_data_dir"]
RUN_FOLDER = config["paths"]["run_folder"]

ALLOWED_ORIGINS = config["server"]["allowed_origins"]

HRRR_PROJ_STRING = config["geo"]["hrrr_proj_string"]