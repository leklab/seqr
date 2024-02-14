from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from seqr.models import Individual, Family
from seqr.views.utils.permissions_utils import get_project_and_check_permissions
from django.db.models import prefetch_related_objects
from collections import defaultdict
from seqr.views.utils.file_utils import parse_file
from seqr.views.utils.json_to_orm_utils import update_model_from_json
from seqr.views.apis.individual_api import INDIVIDUAL_GUID_COL, ASSIGNED_ANALYST_COL, INDIVIDUAL_METADATA_FIELDS, _process_hpo_records
from seqr.views.utils.orm_to_json_utils import _get_json_for_individuals,    _get_json_for_families


def save_individuals_metadata_table_via_command(json_records, user, project, project_guid):
    individual_guids = [record[INDIVIDUAL_GUID_COL] for record in json_records]
    individuals = Individual.objects.filter(
        family__project=project, guid__in=individual_guids)
    individuals_by_guid = {i.guid: i for i in individuals}

    if any(ASSIGNED_ANALYST_COL in record for record in json_records):
        prefetch_related_objects(individuals, 'family')
    family_assigned_analysts = defaultdict(list)

    for record in json_records:
        individual = individuals_by_guid[record[INDIVIDUAL_GUID_COL]]
        update_model_from_json(
            individual, {k: record[k] for k in INDIVIDUAL_METADATA_FIELDS.keys() if k in record}, user=user)
        if record.get(ASSIGNED_ANALYST_COL):
            family_assigned_analysts[record[ASSIGNED_ANALYST_COL]].append(
                individual.family.id)

    response = {
        'individualsByGuid': {
            individual['individualGuid']: individual for individual in _get_json_for_individuals(
                list(individuals_by_guid.values()), user=user, add_hpo_details=True, project_guid=project_guid,
            )},
    }

    if family_assigned_analysts:
        updated_families = set()
        for user in User.objects.filter(email__in=family_assigned_analysts.keys()):
            updated = Family.bulk_update(user, {
                                         'assigned_analyst': user}, id__in=family_assigned_analysts[user.email])
            updated_families.update(updated)

        response['familiesByGuid'] = {
            family['familyGuid']: family for family in _get_json_for_families(
                Family.objects.filter(guid__in=updated_families), user, project_guid=project_guid, has_case_review_perm=False,
            )}

    return response


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('--project', help='Project GUID', required=True)
        parser.add_argument('--input', help='Bams file', required=True)
        parser.add_argument('--user', help='User id number', required=True)

    def handle(self, *args, **options):
        project_guid = options['project']
        filename = options['input']
        user = options['user']

        user = User.objects.get(id=user)
        project = get_project_and_check_permissions(project_guid, user)

        list_of_lists = []
        try:
            with open(filename, 'r') as input:
                list_of_lists = parse_file(filename, input)
            # print(list_of_lists)
            records, errors, warnings = _process_hpo_records(
                list_of_lists, '', project, user)
            
            print(errors, warnings)
            print('{} individuals will be updated'.format(len(records)))

            response = save_individuals_metadata_table_via_command(
                records, user, project, project_guid)
            print(response)

        except Exception as e:
            print(e)

