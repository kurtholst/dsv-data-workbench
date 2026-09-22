"""Environment + Databricks client config (dual-mode: local profile vs Databricks App)."""
import os
from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))

WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "74ec803467a6bcfb")
CATALOG = os.environ.get("DSV_CATALOG", "dsv")
LLM_ENDPOINT = os.environ.get("DSV_LLM_ENDPOINT", "databricks-claude-sonnet-4-6")
ML_ENDPOINT = os.environ.get("DSV_ML_ENDPOINT", "dsv-ftr-risk")
GENIE_SPACE_ID = os.environ.get("DSV_GENIE_SPACE_ID", "01f1b68e95721a3794aeba7cf820b791")

GOLD = f"{CATALOG}.gold"
SILVER = f"{CATALOG}.silver"


def get_workspace_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_PROFILE", "fe-bar")
    return WorkspaceClient(profile=profile)
