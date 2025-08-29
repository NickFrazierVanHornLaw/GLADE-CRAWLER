import os
from dotenv import load_dotenv

load_dotenv()

USERNAME  = os.getenv("GLADE_USERNAME")
PASSWORD  = os.getenv("GLADE_PASSWORD")
HEADLESS  = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO   = int(os.getenv("SLOW_MO", "0"))
START_AT_HOME = os.getenv("START_AT_HOME", "false").lower() == "true"

HOME_URL     = "https://www.glade.ai/"
LOGIN_URL    = "https://app.glade.ai/creator/sign-in"
WORKFLOW_URL = "https://app.glade.ai/dashboard/workflows/user-workflow"

