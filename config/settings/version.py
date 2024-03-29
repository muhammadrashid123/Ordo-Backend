import json
import os
import subprocess

environment = os.getenv("SENTRY_ENVIRONMENT", "UNKNOWN")


BEANSTALK_MANIFEST = "/opt/elasticbeanstalk/deployment/app_version_manifest.json"


def get_beanstalk_version():
    with open(BEANSTALK_MANIFEST) as f:
        data = json.load(f)
    if "VersionLabel" in data:
        label = data["VersionLabel"]
        return label.split("-")[-1]
    runtime_sources = data["RuntimeSources"]
    if len(runtime_sources) != 1:
        raise ValueError()
    inner_object = list(runtime_sources.values())[0]
    if len(inner_object) != 1:
        raise ValueError()
    label = list(inner_object.keys())[0]
    return label.split("-")[-1]


def get_git_version():
    hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    return hash


def get_version():
    if environment == "beantalk":
        return get_beanstalk_version()
    else:
        return get_git_version()


try:
    VERSION = get_version()
except Exception:
    VERSION = "UNKNOWN"
