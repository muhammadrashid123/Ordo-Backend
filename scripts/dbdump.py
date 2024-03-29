import logging
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import dotenv

dotenv.load_dotenv()

ROOT_DIR = pathlib.Path(__file__).parent.parent


def get_db_conn_string():
    logging.info(f"Getting database connection string")
    user = os.getenv("AWS_POSTGRES_USER")
    password = os.getenv("AWS_POSTGRES_PASSWORD")
    host = os.getenv("AWS_POSTGRES_HOST")
    port = os.getenv("AWS_POSTGRES_PORT")
    dbname = os.getenv("AWS_POSTGRES_DB")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def main():
    logging.basicConfig(level="INFO")
    conn_string = get_db_conn_string()
    temp_dir = pathlib.Path(tempfile.mkdtemp())
    temp_filename = temp_dir / "init.sql"
    try:
        logging.info("Dumping database...")
        p = subprocess.Popen(
            [
                "/usr/lib/postgresql/13/bin/pg_dump",
                conn_string,
                "--no-owner",
                "--no-privileges",
                "--verbose",
                "--format",
                "plain",
                "--file",
                str(temp_filename),
            ],
            stderr=sys.stderr,
            stdout=sys.stdout,
        )
        p.wait()
        shutil.move(str(temp_filename), str(ROOT_DIR / f"init.sql"))
    except Exception as e:
        logging.exception(e)
        raise
    finally:
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    main()
