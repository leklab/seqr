"""
seqr integrates with the `PhenoTips <http://phenotips.org>`_ UI so that users can enter
detailed phenotype information for individuals.
The PhenoTips server is installed locally so that it's not visible to the outside network, and
seqr then acts as a proxy for all HTTP requests between the PhenoTips web-based UI (which is
running in users' browser), and the PhenoTips server (running on the internal network).

This proxy setup allows seqr to check authentication and authorization before allowing users to
access patients in PhenoTips, and is similar to how seqr manages access to the SQL database and
other internal systems.

This module implements the proxy functionality + methods for making requests to PhenoTips HTTP APIs.

PhenoTips API docs are at:

https://phenotips.org/DevGuide/API
https://phenotips.org/DevGuide/RESTfulAPI
https://phenotips.org/DevGuide/PermissionsRESTfulAPI
"""

import json
import logging
import re
import requests

import settings

from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.core.exceptions import ObjectDoesNotExist

from reference_data.models import HumanPhenotypeOntology
from seqr.model_utils import update_seqr_model
from seqr.models import Project, CAN_EDIT, CAN_VIEW, Individual
from seqr.views.apis.auth_api import API_LOGIN_REQUIRED_URL
from seqr.views.utils.file_utils import save_uploaded_file
from seqr.views.utils.json_utils import create_json_response
from seqr.views.utils.permissions_utils import check_permissions, get_project_and_check_permissions
from seqr.views.utils.proxy_request_utils import proxy_request

logger = logging.getLogger(__name__)

PHENOTIPS_QUICK_SAVE_URL_REGEX = "/bin/preview/data/(P[0-9]{1,20})"

DO_NOT_PROXY_URL_KEYWORDS = [
    '/delete',
    '/logout',
    '/login',
    '/admin',
    '/CreatePatientRecord',
    '/bin/PatientAccessRightsManagement',
    '/ForgotUsername',
    '/ForgotPassword',
]

FAMILY_ID_COLUMN = 'familyId'
INDIVIDUAL_ID_COLUMN = 'individualId'
HPO_TERMS_PRESENT_COLUMN = 'hpoPresent'
HPO_TERMS_ABSENT_COLUMN = 'hpoAbsent'


@login_required(login_url=API_LOGIN_REQUIRED_URL)
@csrf_exempt
def receive_hpo_table_handler(request, project_guid):
    """Handler for bulk update of hpo terms. This handler parses the records, but doesn't save them in the database.
    Instead, it saves them to a temporary file and sends a 'uploadedFileId' representing this file back to the client.

    Args:
        request (object): Django request object
        project_guid (string): project GUID
    """

    project = get_project_and_check_permissions(project_guid, request.user)
    import traceback, sys
    def process_records(records, **kwargs):
        column_map = {}
        for i, field in enumerate(records[0]):
            key = field.lower()
            if 'family' in key:
                column_map[FAMILY_ID_COLUMN] = i
            elif 'individual' in key:
                column_map[INDIVIDUAL_ID_COLUMN] = i
            elif re.match("hpo.*present", key):
                column_map[HPO_TERMS_PRESENT_COLUMN] = i
            elif re.match("hpo.*absent", key):
                column_map[HPO_TERMS_ABSENT_COLUMN] = i
        if len(column_map) != 4:
            raise ValueError('Invalid header, expected 4 columns and received {}'.format(len(column_map)))
        return [{column: row[index] for column, index in column_map.items()} for row in records[1:]]

    try:
        uploaded_file_id, filename, json_records = save_uploaded_file(request, process_records=process_records)
    except Exception as e:
        _,_, tb = sys.exc_info()
        traceback.print_tb(tb)
        return create_json_response({'errors': [e.message or str(e)], 'warnings': []}, status=400, reason=e.message or str(e))

    updates_by_individual_guid = {}
    missing_individuals = []
    unchanged_individuals = []
    all_hpo_terms = set()
    for record in json_records:
        family_id = record.pop('familyId')
        individual_id = record.pop('individualId')
        id_string = '{individual_id} ({family_id})'.format(individual_id=individual_id, family_id=family_id)
        individual = Individual.objects.filter(
            individual_id=individual_id,
            family__family_id=family_id,
            family__project=project).first()
        if individual:
            features = _parse_hpo_terms(record[HPO_TERMS_PRESENT_COLUMN] or '', 'yes')
            features += _parse_hpo_terms(record[HPO_TERMS_ABSENT_COLUMN] or '', 'no')
            if individual.phenotips_data and features and \
                    _feature_set(features) == _feature_set(json.loads(individual.phenotips_data).get('features', [])):
                unchanged_individuals.append(id_string)
            else:
                all_hpo_terms.update([feature['id'] for feature in features])
                updates_by_individual_guid[individual.guid] = features
        else:
            missing_individuals.append(id_string)

    if not updates_by_individual_guid:
        return create_json_response({
            'errors': ['Unable to find individuals to update for any of the {} parsed individuals'.format(
                len(missing_individuals) + len(unchanged_individuals)
            )],
            'warnings': []
        }, status=400, reason='Unable to find any matching individuals')

    info = ['{} individuals will be updated'.format(len(updates_by_individual_guid))]
    warnings = []
    if missing_individuals:
        warnings.append(
            'Unable to find matching ids for {} individuals. The following entries will not be updated: {}'.format(
                len(missing_individuals), ', '.join(missing_individuals)
            ))
    if unchanged_individuals:
        warnings.append(
            'No changes detected for {} individuals. The following entries will not be updated: {}'.format(
                len(unchanged_individuals), ', '.join(unchanged_individuals)
            ))

    hpo_categories = {hpo.hpo_id: hpo.category_id for hpo in HumanPhenotypeOntology.objects.filter(hpo_id__in=all_hpo_terms)}
    invalid_hpo_terms = []
    for features in updates_by_individual_guid.values():
        for feature in features:
            category = hpo_categories.get(feature['id'])
            if category:
                feature['category'] = category
            else:
                invalid_hpo_terms.append(feature['id'])
    if invalid_hpo_terms:
        warnings.append(
            "The following HPO terms were not found in seqr's HPO data, and while they will be added they may be incorrect: {}".format(
                ', '.join(invalid_hpo_terms)
            ))

    response = {
        'updatesByIndividualGuid': updates_by_individual_guid,
        'uploadedFileId': uploaded_file_id,
        'errors': [],
        'warnings': warnings,
        'info': info,
    }
    return create_json_response(response)


def _parse_hpo_terms(hpo_term_string, observed):
    return [{"id": hpo_term.split('(')[0].strip(), "observed": observed, "type": "phenotype"}
            for hpo_term in hpo_term_string.split(';')] if hpo_term_string else []


def _feature_set(features):
    return set([(feature['id'], feature['observed']) for feature in features])


def update_individual_hpo():
    if record.get(JsonConstants.HPO_TERMS_PRESENT_COLUMN) or record.get(JsonConstants.FINAL_DIAGNOSIS_OMIM_COLUMN):
        # update phenotips hpo ids
        logger.info("Setting PhenoTips HPO Terms to: %s" % (record.get(JsonConstants.HPO_TERMS_PRESENT_COLUMN),))
        set_patient_hpo_terms(
            project,
            individual,
            hpo_terms_present=record.get(JsonConstants.HPO_TERMS_PRESENT_COLUMN, []),
            hpo_terms_absent=record.get(JsonConstants.HPO_TERMS_ABSENT_COLUMN, []),
            final_diagnosis_mim_ids=record.get(JsonConstants.FINAL_DIAGNOSIS_OMIM_COLUMN, []))

        # check HPO ids
        for column_key, column_label in [
            (JsonConstants.HPO_TERMS_PRESENT_COLUMN, 'HPO Terms Present'),
            (JsonConstants.HPO_TERMS_ABSENT_COLUMN, 'HPO Terms Absent')]:
            if r.get(column_key):
                for hpo_id in r[column_key]:
                    if not HumanPhenotypeOntology.objects.filter(hpo_id=hpo_id):
                        warnings.append(
                            "Invalid HPO term \"{hpo_id}\" found in the {column_label} column".format(**locals()))


def _create_patient_if_missing(project, individual):
    """Create a new PhenoTips patient record with the given patient id.

    Args:
        project (Model): seqr Project - used to retrieve PhenoTips credentials
        individual (Model): seqr Individual
    Returns:
        True if patient created
    Raises:
        PhenotipsException: if unable to create patient record
    """
    if phenotips_patient_exists(individual):
        return False

    url = '/rest/patients'
    headers = {"Content-Type": "application/json"}
    data = json.dumps({'external_id': individual.guid})
    auth_tuple = _get_phenotips_uname_and_pwd_for_project(project.phenotips_user_id)

    response_items = _make_api_call('POST', url, auth_tuple=auth_tuple, http_headers=headers, data=data, expected_status_code=201, parse_json_resonse=False)
    patient_id = response_items['Location'].split('/')[-1]
    logger.info("Created PhenoTips record with patient id {patient_id} and external id {external_id}".format(patient_id=patient_id, external_id=individual.guid))

    username_read_only, _ = _get_phenotips_uname_and_pwd_for_project(project.phenotips_user_id, read_only=True)
    _add_user_to_patient(username_read_only, patient_id, allow_edit=False)
    logger.info("Added PhenoTips user {username} to {patient_id}".format(username=username_read_only, patient_id=patient_id))

    update_seqr_model(individual, phenotips_patient_id=patient_id, phenotips_eid=individual.guid)

    return True


def _set_phenotips_patient_id_if_missing(project, individual):
    if individual.phenotips_patient_id:
        return
    patient_json = _get_patient_data(project, individual)
    update_seqr_model(individual, phenotips_patient_id=patient_json['id'])


def _get_patient_data(project, individual):
    """Retrieves patient data from PhenoTips and returns a json obj.
    Args:
        project (Model): seqr Project - used to retrieve PhenoTips credentials
        individual (Model): seqr Individual
    Returns:
        dict: json dictionary containing all PhenoTips information for this patient
    Raises:
        PhenotipsException: if unable to retrieve data from PhenoTips
    """
    url = _phenotips_patient_url(individual)

    auth_tuple = _get_phenotips_uname_and_pwd_for_project(project.phenotips_user_id)
    return _make_api_call('GET', url, auth_tuple=auth_tuple, verbose=False)


def _update_patient_data(project, individual, patient_json):
    """Updates patient data in PhenoTips to the values in patient_json.
    Args:
        project (Model): seqr Project - used to retrieve PhenoTips credentials
        individual (Model): seqr Individual
        patient_json (dict): phenotips patient record like the object returned by get_patient_data(..).
    Raises:
        PhenotipsException: if api call fails
    """
    if not patient_json:
        raise ValueError("patient_json arg is empty")

    url = _phenotips_patient_url(individual)
    patient_json_string = json.dumps(patient_json)

    auth_tuple = _get_phenotips_uname_and_pwd_for_project(project.phenotips_user_id, read_only=False)
    result = _make_api_call('PUT', url, data=patient_json_string, auth_tuple=auth_tuple, expected_status_code=204)

    _update_individual_phenotips_data(individual, patient_json)
    return result


def delete_patient(project, individual):
    """Deletes patient from PhenoTips for the given patient_id.

    Args:
        project (Model): seqr Project - used to retrieve PhenoTips credentials
        individual (Model): seqr Individual
    Raises:
        PhenotipsException: if api call fails
    """
    if phenotips_patient_exists(individual):
        url = _phenotips_patient_url(individual)
        auth_tuple = _get_phenotips_uname_and_pwd_for_project(project.phenotips_user_id, read_only=False)
        return _make_api_call('DELETE', url, auth_tuple=auth_tuple, expected_status_code=204)


def _phenotips_patient_url(individual):
    if individual.phenotips_patient_id:
        return '/rest/patients/{0}'.format(individual.phenotips_patient_id)
    else:
        return '/rest/patients/eid/{0}'.format(individual.phenotips_eid)


def phenotips_patient_exists(individual):
    return individual.phenotips_patient_id or individual.phenotips_eid


def set_patient_hpo_terms(project, individual, hpo_terms_present=[], hpo_terms_absent=[], final_diagnosis_mim_ids=[]):
    """Utility method for specifying a list of HPO IDs for a patient.
    Args:
        project (Model): seqr Project - used to retrieve PhenoTips credentials
        individual (Model): seqr Individual
        hpo_terms_present (list): list of HPO IDs for phenotypes present in this patient (eg. ["HP:00012345", "HP:0012346", ...])
        hpo_terms_absent (list): list of HPO IDs for phenotypes not present in this patient (eg. ["HP:00012345", "HP:0012346", ...])
        final_diagnosis_mim_ids (int): one or more MIM Ids (eg. [105650, ..])
    Raises:
        PhenotipsException: if api call fails
    """
    if not hpo_terms_present or hpo_terms_absent or final_diagnosis_mim_ids:
        return

    _create_patient_if_missing(project, individual)

    patient_json = _get_patient_data(project, individual)

    if hpo_terms_present or hpo_terms_absent:
        features_value = [{"id": hpo_term, "observed": "yes", "type": "phenotype"} for hpo_term in hpo_terms_present]
        features_value += [{"id": hpo_term, "observed": "no", "type": "phenotype"} for hpo_term in hpo_terms_absent]
        patient_json["features"] = features_value

    if final_diagnosis_mim_ids:
        omim_disorders = []
        for mim_id in final_diagnosis_mim_ids:
            if int(mim_id) < 100000:
                raise ValueError("Invalid final_diagnosis_mim_id: %s. Expected a 6-digit number." % str(mim_id))
            omim_disorders.append({'id': 'MIM:%s' % mim_id})
        patient_json["disorders"] = omim_disorders

    _update_patient_data(project, individual, patient_json)


def _add_user_to_patient(username, patient_id, allow_edit=True):
    """Grant a PhenoTips user access to the given patient.

    Args:
        username (string): PhenoTips username to grant access to.
        patient_id (string): PhenoTips internal patient id.
    """
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        'collaborator': 'XWiki.' + str(username),
        'patient': patient_id,
        'accessLevel': 'edit' if allow_edit else 'view',
        'xaction': 'update',
        'submit': 'Update'
    }

    url = '/bin/get/PhenoTips/PatientAccessRightsManagement?outputSyntax=plain'
    _make_api_call(
        'POST',
        url,
        http_headers=headers,
        data=data,
        auth_tuple=(settings.PHENOTIPS_ADMIN_UNAME, settings.PHENOTIPS_ADMIN_PWD),
        expected_status_code=204,
        parse_json_resonse=False,
    )


def create_phenotips_user(username, password):
    """Creates a new user in PhenoTips"""

    headers = { "Content-Type": "application/x-www-form-urlencoded" }
    data = { 'parent': 'XWiki.XWikiUsers' }

    url = '/rest/wikis/xwiki/spaces/XWiki/pages/{username}'.format(username=username)
    _make_api_call(
        'PUT',
        url,
        http_headers=headers,
        data=data,
        auth_tuple=(settings.PHENOTIPS_ADMIN_UNAME, settings.PHENOTIPS_ADMIN_PWD),
        parse_json_resonse=False,
        expected_status_code=[201, 202],
    )

    data = {
        'className': 'XWiki.XWikiUsers',
        'property#password': password,
        #'property#first_name': first_name,
        #'property#last_name': last_name,
        #'property#email': email_address,
    }

    url = '/rest/wikis/xwiki/spaces/XWiki/pages/{username}/objects'.format(username=username)
    return _make_api_call(
        'POST',
        url,
        data=data,
        auth_tuple=(settings.PHENOTIPS_ADMIN_UNAME, settings.PHENOTIPS_ADMIN_PWD),
        parse_json_resonse=False,
        expected_status_code=201,
    )


@login_required
@csrf_exempt
def _phenotips_view_handler(request, project_guid, individual_guid, url_template, permission_level=CAN_VIEW):
    """Requests the PhenoTips PDF for the given patient_id, and forwards PhenoTips' response to the client.

    Args:
        request: Django HTTP request object
        project_guid (string): project GUID for the seqr project containing this individual
        individual_guid (string): individual GUID for the seqr individual corresponding to the desired patient
    """

    project = Project.objects.get(guid=project_guid)
    check_permissions(project, request.user, CAN_VIEW)

    individual = Individual.objects.get(guid=individual_guid)
    _create_patient_if_missing(project, individual)
    _set_phenotips_patient_id_if_missing(project, individual)

    # query string forwarding needed for PedigreeEditor button
    query_string = request.META["QUERY_STRING"]
    url = url_template.format(patient_id=individual.phenotips_patient_id, query_string=query_string)

    auth_tuple = _get_phenotips_username_and_password(request.user, project, permissions_level=permission_level)

    return proxy_request(request, url, headers={}, auth_tuple=auth_tuple, host=settings.PHENOTIPS_SERVER)


@login_required
@csrf_exempt
def phenotips_pdf_handler(request, project_guid, individual_guid):
    """Requests the PhenoTips PDF for the given patient_id, and forwards PhenoTips' response to the client.

    Args:
        request: Django HTTP request object
        project_guid (string): project GUID for the seqr project containing this individual
        individual_guid (string): individual GUID for the seqr individual corresponding to the desired patient
    """
    url_template = "/bin/export/data/{patient_id}?format=pdf&pdfcover=0&pdftoc=0&pdftemplate=PhenoTips.PatientSheetCode"

    return _phenotips_view_handler(request, project_guid, individual_guid, url_template)


@login_required
@csrf_exempt
def phenotips_edit_handler(request, project_guid, individual_guid):
    """Request the PhenoTips Edit page for the given patient_id, and forwards PhenoTips' response to the client.

    Args:
        request: Django HTTP request object
        project_guid (string): project GUID for the seqr project containing this individual
        individual_guid (string): individual GUID for the seqr individual corresponding to the desired patient
    """

    url_template = "/bin/edit/data/{patient_id}?{query_string}"

    return _phenotips_view_handler(request, project_guid, individual_guid, url_template, permission_level=CAN_EDIT)


@login_required(login_url=API_LOGIN_REQUIRED_URL)
@csrf_exempt
def proxy_to_phenotips(request):
    """This django view accepts GET and POST requests and forwards them to PhenoTips"""

    url = request.get_full_path()
    if any([k for k in DO_NOT_PROXY_URL_KEYWORDS if k.lower() in url.lower()]):
        logger.warn("Blocked proxy url: " + str(url))
        return HttpResponse(status=204)
    logger.info("Proxying url: " + str(url))

    # Some PhenoTips endpoints that use HTTP redirects lose the phenotips JSESSION auth cookie
    # along the way, and don't proxy correctly. Using a Session object as below to store the cookies
    # provides a work-around.
    phenotips_session = requests.Session()
    for key, value in request.COOKIES.items():
        phenotips_session.cookies.set(key, value)

    http_response = proxy_request(request, url, data=request.body, session=phenotips_session,
                                  host=settings.PHENOTIPS_SERVER, filter_request_headers=True)

    # if this is the 'Quick Save' request, also save a copy of phenotips data in the seqr SQL db.
    match = re.match(PHENOTIPS_QUICK_SAVE_URL_REGEX, url)
    if match:
        _handle_phenotips_save_request(request, patient_id=match.group(1))

    return http_response


def _make_api_call(
        method,
        url,
        http_headers={},
        data=None,
        auth_tuple=None,
        expected_status_code=200,
        parse_json_resonse=True,
        verbose=False):
    """Utility method for making an API call and then parsing & returning the json response.

    Args:
        method (string): 'GET' or 'POST'
        url (string): url path, starting with '/' (eg. '/bin/edit/data/P0000001')
        data (string): request body - used for POST, PUT, and other such requests.
        auth_tuple (tuple): ("username", "password") pair
        expected_status_code (int or list): expected server response code
        parse_json_resonse (bool): whether to parse and return the json response
        verbose (bool): whether to print details about the request & response
    Returns:
        json object or None if response content is empty
    """

    try:
        response = proxy_request(None, url, headers=http_headers, method=method, scheme='http', data=data,
                                 auth_tuple=auth_tuple, host=settings.PHENOTIPS_SERVER, verbose=verbose)
    except requests.exceptions.RequestException as e:
        raise PhenotipsException(e.message)
    if (isinstance(expected_status_code, int) and response.status_code != expected_status_code) or (
        isinstance(expected_status_code, list) and response.status_code not in expected_status_code):
        raise PhenotipsException("Unable to retrieve %s. response code = %s: %s" % (
            url, response.status_code, response.reason_phrase))

    if parse_json_resonse:
        if not response.content:
            return {}

        try:
            return json.loads(response.content)
        except ValueError as e:
            logger.error("Unable to parse PhenoTips response for %s request to %s" % (method, url))
            raise PhenotipsException("Unable to parse response for %s:\n%s" % (url, e))
    else:
        return dict(response.items())


def _handle_phenotips_save_request(request, patient_id):
    """Update the seqr SQL database record for this patient with the just-saved phenotype data."""

    url = '/rest/patients/%s' % patient_id

    cookie_header = request.META.get('HTTP_COOKIE')
    http_headers = {'Cookie': cookie_header} if cookie_header else {}
    response = proxy_request(request, url, headers=http_headers, method='GET', scheme='http', host=settings.PHENOTIPS_SERVER)
    if response.status_code != 200:
        logger.error("ERROR: unable to retrieve patient json. %s %s %s" % (
            url, response.status_code, response.reason_phrase))
        return

    patient_json = json.loads(response.content)

    try:
        if patient_json.get('external_id'):
            # prefer to use the external id for legacy reasons: some projects shared phenotips
            # records by sharing the phenotips internal id, so in rare cases, the
            # Individual.objects.get(phenotips_patient_id=...) may match multiple Individual records
            individual = Individual.objects.get(phenotips_eid=patient_json['external_id'])
        else:
            individual = Individual.objects.get(phenotips_patient_id=patient_json['id'])

    except ObjectDoesNotExist as e:
        logger.error("ERROR: PhenoTips patient id %s not found in seqr Individuals." % patient_json['id'])
        return

    _update_individual_phenotips_data(individual, patient_json)


def _update_individual_phenotips_data(individual, patient_json):
    """Process and store the given patient_json in the given Individual model.

    Args:
        individual (Individual): Django Individual model
        patient_json (json): json dict representing the patient record in PhenoTips
    """

    # for each HPO term, get the top level HPO category (eg. Musculoskeletal)
    for feature in patient_json.get('features', []):
        hpo_id = feature['id']
        try:
            feature['category'] = HumanPhenotypeOntology.objects.get(hpo_id=hpo_id).category_id
        except ObjectDoesNotExist:
            logger.error("ERROR: PhenoTips HPO id %s not found in seqr HumanPhenotypeOntology table." % hpo_id)

    update_seqr_model(
        individual,
        phenotips_data=json.dumps(patient_json),
        phenotips_patient_id=patient_json['id'],        # phenotips internal id
        phenotips_eid=patient_json.get('external_id'))  # phenotips external id


def _get_phenotips_uname_and_pwd_for_project(phenotips_user_id, read_only=False):
    """Return the PhenoTips username and password for this seqr project"""
    if not phenotips_user_id:
        raise ValueError("Invalid phenotips_user_id: " + str(phenotips_user_id))

    uname = phenotips_user_id + ('_view' if read_only else '')
    pwd = phenotips_user_id + phenotips_user_id

    return uname, pwd


def _get_phenotips_username_and_password(user, project, permissions_level):
    """Checks if user has permission to access the given project, and raises an exception if not.

    Args:
        user (User): the django user object
        project(Model): Project model
        permissions_level (string): 'edit' or 'view'
    Raises:
        PermissionDenied: if user doesn't have permission to access this project.
    Returns:
        2-tuple: PhenoTips username, password that can be used to access patients in this project.
    """
    if permissions_level == CAN_EDIT:
        uname, pwd = _get_phenotips_uname_and_pwd_for_project(project.phenotips_user_id, read_only=False)
    elif permissions_level == CAN_VIEW:
        uname, pwd = _get_phenotips_uname_and_pwd_for_project(project.phenotips_user_id, read_only=True)
    else:
        raise ValueError("Unexpected auth_permissions value: %s" % permissions_level)

    auth_tuple = (uname, pwd)

    return auth_tuple


class PhenotipsException(Exception):
    pass
