import os
import environs

env = environs.Env()
try:
    env.read_env("./.env")
except FileNotFoundError:
    print("No .env file found, using os.environ.")

api_id = int(os.getenv("API_ID") or env.int("API_ID", 0))
api_hash = os.getenv("API_HASH") or env.str("API_HASH", "")

STRINGSESSION = os.getenv("STRINGSESSION") or env.str("STRINGSESSION", "")

second_session = os.getenv("SECOND_SESSION") or env.str("SECOND_SESSION", "")

db_type = os.getenv("DATABASE_TYPE") or env.str("DATABASE_TYPE", "sqlite3")
db_url = os.getenv("DATABASE_URL") or env.str("DATABASE_URL", "")
db_name = os.getenv("DATABASE_NAME") or env.str("DATABASE_NAME", "db.sqlite3")

apiflash_key = os.getenv("APIFLASH_KEY") or env.str("APIFLASH_KEY", "")
rmbg_key = os.getenv("RMBG_KEY") or env.str("RMBG_KEY", "")
vt_key = os.getenv("VT_KEY") or env.str("VT_KEY", "")
gemini_key = os.getenv("GEMINI_KEY") or env.str("GEMINI_KEY", "")
cohere_key = os.getenv("COHERE_KEY") or env.str("COHERE_KEY", "")

pm_limit = int(os.getenv("PM_LIMIT") or env.int("PM_LIMIT", 4))

test_server = bool(os.getenv("TEST_SERVER") or env.bool("TEST_SERVER", False))
modules_repo_branch = os.getenv("MODULES_REPO_BRANCH") or env.str("MODULES_REPO_BRANCH", "master")
