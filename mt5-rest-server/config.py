"""Configuration for the MT5 REST server."""

import os
from dotenv import load_dotenv

# Support ENV_FILE for running multiple instances via NSSM services
env_file = os.environ.get("ENV_FILE", ".env")
load_dotenv(env_file)

API_KEY = os.environ.get("MT5_API_KEY", "")
MT5_LOGIN = int(os.environ.get("MT5_LOGIN", "0"))
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "")
MT5_TERMINAL_PATH = os.environ.get("MT5_TERMINAL_PATH", "")
MT5_MAGIC_NUMBER = int(os.environ.get("MT5_MAGIC_NUMBER", "202603"))
PORT = int(os.environ.get("PORT", "8001"))
