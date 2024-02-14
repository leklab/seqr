from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from seqr.models import Individual, Project
from seqr.views.utils.individual_utils import add_or_update_individuals_and_families
from seqr.views.utils.pedigree_info_utils import parse_pedigree_table

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('--project', help='Project GUID', required=True)
        parser.add_argument('--input', help='Individuals file', required=True)
        parser.add_argument('--user', help='User id number', required=True)
 
    def handle(self, *args, **options):
        project_guid = options['project']
        filename = options['input']
        user = options['user']

        #f = open('/home/ubuntu/tmp/34_individuals.tsv','r')
        f = open(filename,'r')
        #contents = f.readlines()

        list_of_lists = []

        for line in f:
            inner_list = [elt.strip() for elt in line.split('\t')]
            list_of_lists.append(inner_list)


        user = User.objects.get(id=user)
        project = Project.objects.get(guid=project_guid)

        try:
            json_records, warnings = parse_pedigree_table(list_of_lists, filename=filename, user=user)
            updated_individuals, updated_families, updated_notes = add_or_update_individuals_and_families(project, json_records, user)

            print(updated_individuals, updated_families, updated_notes)

        except Exception as e:
            print(str(e))

        #print(json_records)



