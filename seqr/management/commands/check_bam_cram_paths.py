from django.core.management.base import BaseCommand

from seqr.models import IgvSample
from seqr.views.utils.dataset_utils import validate_alignment_dataset_path

import collections
import hail as hl
import logging
import tqdm

logger = logging.getLogger(__name__)

hl.init(log="/dev/null")


class Command(BaseCommand):
    help = 'Checks all gs:// bam or cram paths and, if a file no longer exists, deletes the path from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '-d',
            '--dry-run',
            action="store_true",
            help='Only print missing paths without updating the database',
        )
        parser.add_argument('args', nargs='*', help='only check paths in these project name(s)')

    def handle(self, *args, **options):
        samples = (IgvSample.objects.filter(
            individual__family__project__name__in=args,
        ) if args else IgvSample.objects.all()).prefetch_related('individual', 'individual__family__project')

        missing_counter = collections.defaultdict(int)
        for sample in tqdm.tqdm(samples, unit=" samples"):
            if sample.file_path and sample.file_path.startswith("gs://") and not hl.hadoop_is_file(sample.file_path):
                individual_id = sample.individual.individual_id
                project = sample.individual.family.project.name
                missing_counter[project] += 1
                logger.info('Individual: {}  file not found: {}'.format(individual_id, sample.file_path))
                if not options.get('dry_run'):
                    sample.file_path = ""  # TODO is it better to just delete the sample record?
                    sample.save()

        logger.info('---- DONE ----')
        logger.info('Checked {} samples'.format(len(samples)))
        if missing_counter:
            logger.info('{} files not found:'.format(sum(missing_counter.values())))
            for project_name, c in sorted(missing_counter.items(), key=lambda t: -t[1]):
                logger.info('   {} in {}'.format(c, project_name))
