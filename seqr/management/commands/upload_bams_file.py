from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from seqr.models import IgvSample, Individual, Project
from seqr.views.utils.file_utils import parse_file
from collections import defaultdict
from seqr.views.utils.json_to_orm_utils import get_or_create_model_from_json
from seqr.views.utils.permissions_utils import get_project_and_check_permissions
from seqr.utils.file_utils import does_file_exist
from seqr.views.apis.igv_api import SAMPLE_TYPE_MAP
import sys


def process_alignment_records_via_command(rows):
    invalid_row = next((row for row in rows if not 2 <= len(row) <= 3), None)
    if invalid_row:
        raise ValueError("Must contain 2 or 3 columns: " +
                         ', '.join(invalid_row))
    parsed_records = defaultdict(list)
    for row in rows:
        parsed_records[row[0]].append(
            {'filePath': row[1], 'sampleId': row[2] if len(row) > 2 else None})
    return parsed_records


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
            print(list_of_lists)
            # format of individual_dataset_mapping:
            # {individual_id: [{'filePath': filePath, 'sampleId': None}]}
            individual_dataset_mapping = process_alignment_records_via_command(
                list_of_lists)
            # print(individual_dataset_mapping)

            matched_individuals = Individual.objects.filter(
                family__project=project, individual_id__in=individual_dataset_mapping.keys())
            # print(matched_individuals)
            unmatched_individuals = set(individual_dataset_mapping.keys(
            )) - {i.individual_id for i in matched_individuals}
            if len(unmatched_individuals) > 0:
                raise Exception('The following Individual IDs do not exist: {}'.format(
                    ", ".join(unmatched_individuals)))

            existing_sample_files = defaultdict(set)
            for sample in IgvSample.objects.select_related('individual').filter(individual__in=matched_individuals):
                existing_sample_files[sample.individual.individual_id].add(
                    sample.file_path)

            # print('existing_sample_files')
            # print(existing_sample_files)

            unchanged_rows = set()
            for individual_id, updates in individual_dataset_mapping.items():
                unchanged_rows.update([
                    (individual_id, update['filePath']) for update in updates
                    if update['filePath'] in existing_sample_files[individual_id]
                ])

            if unchanged_rows:
                print('No change detected for {} rows'.format(len(unchanged_rows)))

            all_updates = []
            for i in matched_individuals:
                all_updates += [
                    dict(individualGuid=i.guid, **update) for update in individual_dataset_mapping[i.individual_id]
                    if (i.individual_id, update['filePath']) not in unchanged_rows
                ]

            # print(all_updates)
            
            for record in all_updates:
                individual = Individual.objects.get(
                    guid=record.get('individualGuid'))
                file_path = record.get('filePath')
                sample_id = record.get('sampleId')
                sample_type = next(
                    (st for suffix, st in SAMPLE_TYPE_MAP if file_path.endswith(suffix)), None)

                if not sample_type:
                    print('Invalid file extension for "{}" - valid extensions are {}'.format(
                        file_path, ', '.join([suffix for suffix, _ in SAMPLE_TYPE_MAP])))
                    continue
                if not does_file_exist(file_path, user=user):
                    print('Error accessing "{}"'.format(file_path))
                    continue
                
                sample, created = get_or_create_model_from_json(IgvSample, create_json={'individual': individual, 'sample_type': sample_type},  update_json={
                                                                'file_path': file_path, 'sample_id': sample_id}, user=user)
                print(sample, created)

        except Exception as e:
            print(e)

