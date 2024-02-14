import gzip
import os
import subprocess # nosec

from seqr.utils.logging_utils import SeqrLogger

from urllib.parse import urlparse
import boto3

logger = SeqrLogger(__name__)


def run_command(command, user=None):
    logger.info('==> {}'.format(command), user)
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True) # nosec


def _run_gsutil_command(command, gs_path, gunzip=False, user=None):
    #  Anvil buckets are requester-pays and we bill them to the anvil project
    google_project = get_google_project(gs_path)
    project_arg = '-u {} '.format(google_project) if google_project else ''
    command = 'gsutil {project_arg}{command} {gs_path}'.format(
        project_arg=project_arg, command=command, gs_path=gs_path,
    )
    if gunzip:
        command += " | gunzip -c -q - "

    return run_command(command, user=user)


def is_google_bucket_file_path(file_path):
    return file_path.startswith("gs://")

def _is_s3_file_path(file_path):
    return file_path.startswith("s3://")

def parse_s3_path(s3path):
    parsed = urlparse(s3path)
    bucket = parsed.netloc
    path = parsed.path[1:]
    object_list = path.split('/')
    filename = object_list[-1]
    return {
        "bucket" : bucket,
        "key" : path,
        "filename" : filename
    }

#Need cross AWS account access
def create_s3_session():
    sts_client = boto3.client('sts')
    #hard-coded so can fix
    assumed_role_object = sts_client.assume_role(
        RoleArn='arn:aws:iam::905042445333:role/assumerole_by_seqr_account',
        RoleSessionName='seqr'
    )

    #print(assumed_role_object)
    credentials = assumed_role_object['Credentials']

    session = boto3.Session(
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken']
    )

    return session

def get_google_project(gs_path):
    return 'anvil-datastorage' if gs_path.startswith('gs://fc-secure') else None

def does_file_exist(file_path, user=None):
    if is_google_bucket_file_path(file_path):
        process = _run_gsutil_command('ls', file_path, user=user)
        success = process.wait() == 0
        if not success:
            errors = [line.decode('utf-8').strip() for line in process.stdout]
            logger.info(' '.join(errors), user)
        return success
    elif _is_s3_file_path(file_path):
        #s3_client = boto3.client('s3')
        s3_client = create_s3_session().client('s3')
        parts = parse_s3_path(file_path)
        response = s3_client.list_objects(
            Bucket = parts['bucket'],
            Prefix = parts['key']
        )
        return 'Contents' in response and len(response['Contents']) > 0

    return os.path.isfile(file_path)


def file_iter(file_path, byte_range=None, raw_content=False, user=None):
    if is_google_bucket_file_path(file_path):
        for line in _google_bucket_file_iter(file_path, byte_range=byte_range, raw_content=raw_content, user=user):
            yield line
    elif _is_s3_file_path(file_path):
        for line in _s3_file_iter(file_path,byte_range=byte_range):
            yield line
    elif byte_range:
        command = 'dd skip={offset} count={size} bs=1 if={file_path}'.format(
            offset=byte_range[0],
            size=byte_range[1]-byte_range[0],
            file_path=file_path,
        )
        process = run_command(command, user=user)
        for line in process.stdout:
            yield line
    else:
        mode = 'rb' if raw_content else 'r'
        open_func = gzip.open if file_path.endswith("gz") else open
        with open_func(file_path, mode) as f:
            for line in f:
                yield line


def _google_bucket_file_iter(gs_path, byte_range=None, raw_content=False, user=None):
    """Iterate over lines in the given file"""
    range_arg = ' -r {}-{}'.format(byte_range[0], byte_range[1]) if byte_range else ''
    process = _run_gsutil_command(
        'cat{}'.format(range_arg), gs_path, gunzip=gs_path.endswith("gz") and not raw_content, user=user)
    for line in process.stdout:
        if not raw_content:
            line = line.decode('utf-8')
        yield line

def _s3_file_iter(file_path, byte_range = None):
    logger.info("Iterating over s3 path: " + file_path,user=None)

    #client = boto3.client('s3')
    client = create_s3_session().client('s3')

    range_arg = f"bytes={byte_range[0]}-{byte_range[1]}" if byte_range else ''
    logger.info("Byte range for s3: " + range_arg, user=None)
    parts = parse_s3_path(file_path)
    #t = tempfile.TemporaryFile()
    r = client.get_object(
        Bucket=parts['bucket'],
        Key=parts['key'],
        Range=range_arg,
    )
    for line in r['Body']:
        yield line

def mv_file_to_gs(local_path, gs_path, user=None):
    command = 'mv {}'.format(local_path)
    _run_gsutil_with_wait(command, gs_path, user)


def get_gs_file_list(gs_path, user=None):
    gs_path = gs_path.rstrip('/')
    command = 'ls'

    # If a bucket is empty gsutil throws an error when running ls with ** instead of returning an empty list
    subfolders = _run_gsutil_with_wait(command, gs_path, user, get_stdout=True)
    if not subfolders:
        return []

    all_lines = _run_gsutil_with_wait(command, f'{gs_path}/**', user, get_stdout=True)
    return [line for line in all_lines if line.startswith(gs_path)]


def _run_gsutil_with_wait(command, gs_path, user=None, get_stdout=False):
    if not is_google_bucket_file_path(gs_path):
        raise Exception('A Google Storage path is expected.')
    process = _run_gsutil_command(command, gs_path, user=user)
    if process.wait() != 0:
        errors = [line.decode('utf-8').strip() for line in process.stdout]
        raise Exception('Run command failed: ' + ' '.join(errors))
    if get_stdout:
        return [line.decode('utf-8').rstrip('\n') for line in process.stdout]
    return process
