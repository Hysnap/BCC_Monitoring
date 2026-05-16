"""Project-wide globals and Streamlit session bootstrap.

This module is the single place for shared project paths, filenames, defaults,
and session-state initialisation. It is intentionally self-contained so it can
be imported without a separate config module.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

import streamlit as st

try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx
except Exception:  # pragma: no cover - fallback when Streamlit internals differ
    get_script_run_ctx = None


LOGGER = logging.getLogger("sl_core.global_variables")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_NAME = PROJECT_ROOT.name


def _build_directories() -> Dict[str, Path]:
    base_dir = PROJECT_ROOT
    output_dir = base_dir / "output"
    return {
        "base_dir": base_dir,
        "reference_dir": base_dir / "reference_files",
        "data_dir": output_dir / "data",
        "output_dir": output_dir,
        "logs_dir": base_dir / "logs",
        "raw_html_dir": output_dir / "raw_html",
        "checkpoints_dir": output_dir / "checkpoints",
        "components_dir": base_dir / "sl_core" / "components",
        "app_pages_dir": base_dir / "app_pages",
        "utils_dir": base_dir / "sl_core" / "utils",
        "publication_dir": output_dir / "publication",
        "election_output_dir": output_dir / "election_2026_all_wards",
    }


DIRECTORIES = _build_directories()
FILENAMES = {
    "output": {
        "people": "people.csv",
        "party_history": "party_history.csv",
        "election_standings": "election_standings.csv",
        "ward_summaries": "ward_summaries.csv",
        "manifest": "manifest.json",
        "checkpoint": "checkpoint.json",
    },
    "reference": {
        "credentials": "admin_credentials.json",
        "text": "admin_text.json",
    },
    "logs": {
        "app_log": "app_log.log",
    },
    "legacy": {
        "original_data": "original_data.csv",
        "mp_party_memberships": "mp_party_memberships.csv",
        "mp_party_memberships_cleaned": "mp_party_memberships_cleaned.csv",
    },
}

PLACEHOLDER_DATE = "1900-01-01"
PLACEHOLDER_ID = "UNKNOWN"
THRESHOLDS = {}
DATA_REMAPPINGS = {}
FILTER_DEF = {"Cash_ftr": None}
SECURITY = {
    "is_admin": False,
    "admin_username": "admin",
    "admin_password_hash": "",
}
PERC_TARGET = 0
perc_target = PERC_TARGET
RERUN_MP_PARTY_MEMBERSHIP = False
ELECTORAL_CYCLE_RULES = {}


def _reference_file_path(filename: str) -> str:
    return str(DIRECTORIES["reference_dir"] / filename)


TEXT_FILE = _reference_file_path(FILENAMES["reference"]["text"])
CREDENTIALS_FILE = _reference_file_path(FILENAMES["reference"]["credentials"])
ORIGINAL_DATA_FNAME = str(DIRECTORIES["data_dir"] / FILENAMES["legacy"]["original_data"])
MP_PARTY_MEMBERSHIPS_FNAME = str(
    DIRECTORIES["reference_dir"] / FILENAMES["legacy"]["mp_party_memberships"]
)
MP_PARTY_MEMBERSHIPS_FILE_PATH = str(
    DIRECTORIES["output_dir"] / FILENAMES["legacy"]["mp_party_memberships_cleaned"]
)


def _in_streamlit_context() -> bool:
    if get_script_run_ctx is None:
        return False
    try:
        return get_script_run_ctx() is not None
    except Exception:
        return False


def _ensure_directories_exist() -> None:
    for path in DIRECTORIES.values():
        Path(path).mkdir(parents=True, exist_ok=True)


def _seed_session_state(values: Dict[str, Any]) -> None:
    if not _in_streamlit_context():
        return
    for key, value in values.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _seed_module_globals(values: Dict[str, Any]) -> None:
    globals().update(values)


def build_project_globals() -> Dict[str, Any]:
    """Return the canonical global variables for this project."""
    return {
        "PROJECT_NAME": PROJECT_NAME,
        "PROJECT_ROOT": PROJECT_ROOT,
        "BASE_DIR": DIRECTORIES["base_dir"],
        "DIRECTORIES": DIRECTORIES,
        "FILENAMES": FILENAMES,
        "TEXT_FILE": TEXT_FILE,
        "CREDENTIALS_FILE": CREDENTIALS_FILE,
        "ORIGINAL_DATA_FNAME": ORIGINAL_DATA_FNAME,
        "MP_PARTY_MEMBERSHIPS_FNAME": MP_PARTY_MEMBERSHIPS_FNAME,
        "MP_PARTY_MEMBERSHIPS_FILE_PATH": MP_PARTY_MEMBERSHIPS_FILE_PATH,
        "PLACEHOLDER_DATE": PLACEHOLDER_DATE,
        "PLACEHOLDER_ID": PLACEHOLDER_ID,
        "THRESHOLDS": THRESHOLDS,
        "DATA_REMAPPINGS": DATA_REMAPPINGS,
        "FILTER_DEF": FILTER_DEF,
        "SECURITY": SECURITY,
        "PERC_TARGET": PERC_TARGET,
        "perc_target": perc_target,
        "RERUN_MP_PARTY_MEMBERSHIP": RERUN_MP_PARTY_MEMBERSHIP,
        "ELECTORAL_CYCLE_RULES": ELECTORAL_CYCLE_RULES,
        # Election scraping defaults
        "ELECTION_START_URL": "https://www.birmingham.gov.uk/info/50385/election_2026_-_results_by_ward",
        "ELECTION_OUTPUT_DIR": DIRECTORIES["election_output_dir"],
        "RAW_HTML_DIR": DIRECTORIES["raw_html_dir"],
        "CHECKPOINTS_DIR": DIRECTORIES["checkpoints_dir"],
        "PUBLISH_DIR": DIRECTORIES["publication_dir"],
        "DEFAULT_DELAY_MIN": 2.5,
        "DEFAULT_DELAY_MAX": 6.0,
        "DEFAULT_TIMEOUT_MS": 60000,
    }


def initialize_session_state() -> Dict[str, Any]:
    """Initialise module globals and Streamlit session state defaults."""
    values = build_project_globals()
    _ensure_directories_exist()
    _seed_module_globals(values)
    _seed_session_state(values)
    LOGGER.debug("Project globals initialised for %s", PROJECT_NAME)
    return values


def init_state_var(var_name: str, config_value: Any) -> Any:
    """Backwards-compatible helper for older call sites."""
    if _in_streamlit_context() and var_name not in st.session_state:
        st.session_state[var_name] = config_value
    globals()[var_name] = config_value
    return config_value


def get_global(var_name: str, default: Any = None) -> Any:
    """Return a project global from module state or Streamlit session state."""
    if _in_streamlit_context() and var_name in st.session_state:
        return st.session_state[var_name]
    return globals().get(var_name, default)


initialize_session_state()
