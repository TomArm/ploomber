"""
Implementation of:

$ plomber cloud

This command runs a bunch of pip/conda commands (depending on what's available)
and it does the *right thing*: creating a new environment if needed, and
locking dependencies.
"""
import json
import uuid
import warnings
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
import http.client as httplib
import click
from functools import wraps

import humanize

from ploomber.telemetry import telemetry
from ploomber.telemetry.telemetry import check_dir_exist, CONF_DIR, \
    DEFAULT_USER_CONF, read_conf_file, update_conf_file, parse_dag

CLOUD_APP_URL = 'ggeheljnx2.execute-api.us-east-1.amazonaws.com'
PIPELINES_RESOURCE = '/prod/pipelines'
headers = {'Content-type': 'application/json'}


def get_key():
    """
    This gets the user cloud api key, returns None if doesn't exist.
    config.yaml is the default user conf file to fetch from.
    """
    user_conf_path = Path(check_dir_exist(CONF_DIR), DEFAULT_USER_CONF)
    conf = read_conf_file(user_conf_path)
    key = conf.get('cloud_key', None)

    return key


@telemetry.log_call('set-key')
def set_key(user_key):
    """
    Sets the user cloud api key, if key isn't valid 16 chars length, returns.
    Valid keys are set in the config.yaml (default user conf file).
    """
    _set_key(user_key)


def _set_key(user_key):
    # Validate key
    if not user_key or len(user_key) != 22:
        warnings.warn("The API key is malformed.\n"
                      "Please validate your key or contact the admin\n")
        return

    user_key_dict = {'cloud_key': user_key}
    user_conf_path = Path(check_dir_exist(CONF_DIR), DEFAULT_USER_CONF)
    update_conf_file(user_conf_path, user_key_dict)
    click.secho("Key was stored {}".format(user_key))


def get_last_run(timestamp):
    try:
        if timestamp is not None:
            dt = datetime.fromtimestamp(float(timestamp))

            date_h = dt.strftime('%b %d, %Y at %H:%M')
            time_h = humanize.naturaltime(dt)
            last_run = '{} ({})'.format(time_h, date_h)
        else:
            last_run = 'Has not been run'
        return last_run
    except ValueError:
        return timestamp


@telemetry.log_call('get-pipeline')
def get_pipeline(pipeline_id=None, verbose=None):
    """
    Gets a user pipeline via the cloud api key. Validates the key.
    The response is the pipeline instance along with a print statement.
    If the pipeline wasn't found print the server response.
    """
    # Validate API key
    key = get_key()
    if not key:
        return "No cloud API Key was found: {}".format(key)

    # Get pipeline API call
    conn = httplib.HTTPSConnection(CLOUD_APP_URL, timeout=3)
    try:
        headers = {'api_key': key}
        if pipeline_id:
            headers['pipeline_id'] = pipeline_id
        if verbose:
            headers['verbose'] = True
        conn.request("GET", PIPELINES_RESOURCE, headers=headers)

        content = conn.getresponse().read()
        pipeline = json.loads(content)
        for item in pipeline:
            item['updated'] = get_last_run(item['updated'])
        return pipeline
    except JSONDecodeError:
        return "Issue fetching pipeline {}".format(content)
    finally:
        conn.close()


@telemetry.log_call('write-pipeline')
def write_pipeline(pipeline_id,
                   status,
                   log=None,
                   pipeline_name=None,
                   dag=None):
    """
    Updates a user pipeline via the cloud api key. Validates the key.
    The response is the pipeline id if the update was successful.
    If the pipeline wasn't written/updated, the result will contain the error.
    """
    return _write_pipeline(pipeline_id, status, log, pipeline_name, dag)


def _write_pipeline(pipeline_id,
                    status,
                    log=None,
                    pipeline_name=None,
                    dag=None):
    # Validate API key & inputs
    key = get_key()
    if not key:
        return "No cloud API Key was found: {}".format(key)
    if not pipeline_id:
        return "No input pipeline_id: {}".format(key)
    elif not status:
        return "No input pipeline status: {}".format(key)

    # Write pipeline API call
    conn = httplib.HTTPSConnection(CLOUD_APP_URL, timeout=3)
    try:
        headers['api_key'] = key
        body = {
            "pipeline_id": pipeline_id,
            "status": status,
        }
        if pipeline_name:
            body['pipeline_name'] = pipeline_name
        if log:
            body['log'] = log
        if dag:
            body['dag'] = dag
        conn.request("POST",
                     PIPELINES_RESOURCE,
                     body=json.dumps(body),
                     headers=headers)
        content = conn.getresponse().read()
        return content
    except Exception as e:
        return "Error fetching pipeline {}".format(e)
    finally:
        conn.close()


@telemetry.log_call('delete-pipeline')
def delete_pipeline(pipeline_id):
    """
    Updates a user pipeline via the cloud api key. Validates the key.
    The response is the pipeline id if the update was successful.
    If the pipeline wasn't written/updated, the result will contain the error.
    """
    # Validate inputs
    key = get_key()
    if not key:
        return "No cloud API Key was found: {}".format(key)
    if not pipeline_id:
        return "No input pipeline_id: {}".format(key)

    # Delete pipeline API call
    conn = httplib.HTTPSConnection(CLOUD_APP_URL, timeout=3)
    try:
        headers['api_key'] = key
        headers['pipeline_id'] = pipeline_id
        conn.request("DELETE", PIPELINES_RESOURCE, headers=headers)
        content = conn.getresponse().read()
        return content
    except Exception as e:
        return "Issue deleting pipeline {}".format(e)
    finally:
        conn.close()


def cloud_wrapper(payload=False):
    """Runs a function and logs the pipeline status
    """
    def _cloud_call(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _payload = dict()
            pid = str(uuid.uuid4())

            res = str(_write_pipeline(pipeline_id=pid, status='started'))
            if 'Error' in res:
                warnings.warn(res)

            try:
                if payload:
                    result = func(_payload, *args, **kwargs)
                else:
                    result = func(*args, **kwargs)
            except Exception as e:
                res = str(
                    _write_pipeline(pipeline_id=pid,
                                    status='error',
                                    log=str(e.args)))
                if 'Error' in res:
                    warnings.warn(res)
                raise e
            else:

                dag = parse_dag(result)
                res = str(
                    _write_pipeline(pipeline_id=pid,
                                    status='finished',
                                    dag=dag))
                if 'Error' in str(res):
                    warnings.warn(res)
            return result

        return wrapper

    return _cloud_call


get_pipeline('9f9e18e0-d027-4827-bd4d-1908f294bca2', False)