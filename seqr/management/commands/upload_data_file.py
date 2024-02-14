from django.core.management.base import BaseCommand, CommandError
from seqr.models import Individual, Project
from seqr.views.utils.individual_utils import add_or_update_individuals_and_families

import json

def _parse_sex(sex):
    if sex == '1' or sex.upper().startswith('M'):
        return 'M'
    elif sex == '2' or sex.upper().startswith('F'):
        return 'F'
    elif sex == '0' or not sex or sex.lower() in {'unknown', 'prefer_not_answer'}:
        return 'U'
    return None


def _parse_affected(affected):
    if affected == '1' or affected.upper() == "U" or affected.lower() == 'unaffected':
        return 'N'
    elif affected == '2' or affected.upper().startswith('A'):
        return 'A'
    elif affected == '0' or not affected or affected.lower() == 'unknown':
        return 'U'
    return None

class JsonConstants:
    FAMILY_ID_COLUMN = 'familyId'
    INDIVIDUAL_ID_COLUMN = 'individualId'
    PREVIOUS_INDIVIDUAL_ID_COLUMN = 'previousIndividualId'
    PATERNAL_ID_COLUMN = 'paternalId'
    MATERNAL_ID_COLUMN = 'maternalId'
    SEX_COLUMN = 'sex'
    AFFECTED_COLUMN = 'affected'
    SAMPLE_ID_COLUMN = 'sampleId'
    NOTES_COLUMN = 'notes'
    FAMILY_NOTES_COLUMN = 'familyNotes'
    CODED_PHENOTYPE_COLUMN = 'codedPhenotype'
    PROBAND_RELATIONSHIP = 'probandRelationship'
    MATERNAL_ETHNICITY = 'maternalEthnicity'
    PATERNAL_ETHNICITY = 'paternalEthnicity'
    BIRTH_YEAR = 'birthYear'
    DEATH_YEAR = 'deathYear'
    ONSET_AGE = 'onsetAge'
    AFFECTED_RELATIVES = 'affectedRelatives'
    PRIMARY_BIOSAMPLE = 'primaryBiosample'
    ANALYTE_TYPE = 'analyteType'
    TISSUE_AFFECTED_STATUS = 'tissueAffectedStatus'

    JSON_COLUMNS = {MATERNAL_ETHNICITY, PATERNAL_ETHNICITY, BIRTH_YEAR, DEATH_YEAR, ONSET_AGE, AFFECTED_RELATIVES}

    FORMAT_COLUMNS = {
        SEX_COLUMN: _parse_sex,
        AFFECTED_COLUMN: _parse_affected,
        PATERNAL_ID_COLUMN: lambda value: value if value != '.' else '',
        MATERNAL_ID_COLUMN: lambda value: value if value != '.' else '',
        PROBAND_RELATIONSHIP: lambda value: RELATIONSHIP_REVERSE_LOOKUP.get(value.lower()),
        PRIMARY_BIOSAMPLE: lambda value: next(
            (code for code, uberon_code in Individual.BIOSAMPLE_CHOICES if value.startswith(uberon_code)), None),
        ANALYTE_TYPE: Individual.ANALYTE_REVERSE_LOOKUP.get,
        TISSUE_AFFECTED_STATUS: {'Yes': True, 'No': False}.get,
    }
    FORMAT_COLUMNS.update({col: json.loads for col in JSON_COLUMNS})

    COLUMN_SUBSTRINGS = [
        (FAMILY_ID_COLUMN, ['family']),
        (PREVIOUS_INDIVIDUAL_ID_COLUMN, ['indiv', 'previous']),
        (INDIVIDUAL_ID_COLUMN, ['indiv']),
        (PATERNAL_ID_COLUMN, ['father']),
        (PATERNAL_ID_COLUMN, ['paternal']),
        (MATERNAL_ID_COLUMN, ['mother']),
        (MATERNAL_ID_COLUMN, ['maternal']),
        (SEX_COLUMN, ['sex']),
        (SEX_COLUMN, ['gender']),
        (TISSUE_AFFECTED_STATUS, ['tissue', 'affected', 'status']),
        (PRIMARY_BIOSAMPLE, ['primary', 'biosample']),
        (ANALYTE_TYPE, ['analyte', 'type']),
        (AFFECTED_COLUMN, ['affected']),
        (CODED_PHENOTYPE_COLUMN, ['coded', 'phenotype']),
        (PROBAND_RELATIONSHIP, ['proband', 'relation']),
    ]




def _is_header_row(row):
    """Checks if the 1st row of a table is a header row

    Args:
        row (string): 1st row of a table
    Returns:
        True if it's a header row rather than data
    """
    row = row.lower()
    if "family" in row and ("indiv" in row or "participant" in row):
        return True
    else:
        return False


def _convert_fam_file_rows_to_json(rows):
    """Parse the values in rows and convert them to a json representation.

    Args:
        rows (list): a list of rows where each row is a list of strings corresponding to values in the table

    Returns:
        list: a list of dictionaries with each dictionary being a json representation of a parsed row.
            For example:
               {
                    'familyId': family_id,
                    'individualId': individual_id,
                    'paternalId': paternal_id,
                    'maternalId': maternal_id,
                    'sex': sex,
                    'affected': affected,
                    'notes': notes,
                    'codedPhenotype': ,
                    'hpoTermsPresent': [...],
                    'hpoTermsAbsent': [...],
                    'fundingSource': [...],
                    'caseReviewStatus': [...],
                }

    Raises:
        ValueError: if there are unexpected values or row sizes
    """
    json_results = []
    for i, row_dict in enumerate(rows):

        json_record = _parse_row_dict(row_dict, i)

        # validate
        if not json_record.get(JsonConstants.FAMILY_ID_COLUMN):
            raise ValueError("Family Id not specified in row #%d:\n%s" % (i+1, json_record))
        if not json_record.get(JsonConstants.INDIVIDUAL_ID_COLUMN):
            raise ValueError("Individual Id not specified in row #%d:\n%s" % (i+1, json_record))

        json_results.append(json_record)

    return json_results

def _parse_row_dict(row_dict, i):
    json_record = {}
    for key, value in row_dict.items():
        full_key = key
        key = key.lower()
        value = (value or '').strip()

        if full_key in JsonConstants.JSON_COLUMNS:
            column = full_key
        elif key == JsonConstants.FAMILY_NOTES_COLUMN.lower():
            column = JsonConstants.FAMILY_NOTES_COLUMN
        elif key.startswith("notes"):
            column = JsonConstants.NOTES_COLUMN
        else:
            column = next((
                col for col, substrings in JsonConstants.COLUMN_SUBSTRINGS
                if all(substring in key for substring in substrings)
            ), None)

        if column:
            format_func = JsonConstants.FORMAT_COLUMNS.get(column)
            if format_func and (value or column in {JsonConstants.SEX_COLUMN, JsonConstants.AFFECTED_COLUMN}):
                parsed_value = format_func(value)
                if parsed_value is None and column not in JsonConstants.JSON_COLUMNS:
                    raise ValueError(f'Invalid value "{value}" for {_to_snake_case(column)} in row #{i + 1}')
                value = parsed_value
            json_record[column] = value
    return json_record


def validate_fam_file_records(records, fail_on_warnings=False):
    """Basic validation such as checking that parents have the same family id as the child, etc.

    Args:
        records (list): a list of dictionaries (see return value of #process_rows).

    Returns:
        dict: json representation of any errors, warnings, or info messages:
            {
                'errors': ['error text1', 'error text2', ...],
                'warnings': ['warning text1', 'warning text2', ...],
                'info': ['info message', ...],
            }
    """
    records_by_id = {r[JsonConstants.PREVIOUS_INDIVIDUAL_ID_COLUMN]: r for r in records
                     if r.get(JsonConstants.PREVIOUS_INDIVIDUAL_ID_COLUMN)}
    records_by_id.update({r[JsonConstants.INDIVIDUAL_ID_COLUMN]: r for r in records})

    errors = []
    warnings = []
    for r in records:
        individual_id = r[JsonConstants.INDIVIDUAL_ID_COLUMN]
        family_id = r.get(JsonConstants.FAMILY_ID_COLUMN) or r['family']['familyId']

        # check proband relationship has valid gender
        if r.get(JsonConstants.PROBAND_RELATIONSHIP) and r.get(JsonConstants.SEX_COLUMN):
            invalid_choices = {}
            if r[JsonConstants.SEX_COLUMN] == Individual.SEX_MALE:
                invalid_choices = Individual.FEMALE_RELATIONSHIP_CHOICES
            elif r[JsonConstants.SEX_COLUMN] == Individual.SEX_FEMALE:
                invalid_choices = Individual.MALE_RELATIONSHIP_CHOICES
            if invalid_choices and r[JsonConstants.PROBAND_RELATIONSHIP] in invalid_choices:
                errors.append(
                    'Invalid proband relationship "{relationship}" for {individual_id} with given gender {sex}'.format(
                        relationship=Individual.RELATIONSHIP_LOOKUP[r[JsonConstants.PROBAND_RELATIONSHIP]],
                        individual_id=individual_id,
                        sex=dict(Individual.SEX_CHOICES)[r[JsonConstants.SEX_COLUMN]]
                    ))

        # check maternal and paternal ids for consistency
        for parent_id_type, parent_id, expected_sex in [
            ('father', r.get(JsonConstants.PATERNAL_ID_COLUMN), 'M'),
            ('mother', r.get(JsonConstants.MATERNAL_ID_COLUMN), 'F')
        ]:
            if not parent_id:
                continue

            # is there a separate record for the parent id?
            if parent_id not in records_by_id:
                warnings.append("%(parent_id)s is the %(parent_id_type)s of %(individual_id)s but doesn't have a separate record in the table" % locals())
                continue

            # is the parent the same individuals
            if parent_id == individual_id:
                errors.append('{} is recorded as their own {}'.format(parent_id, parent_id_type))

            # is father male and mother female?
            if JsonConstants.SEX_COLUMN in records_by_id[parent_id]:
                actual_sex = records_by_id[parent_id][JsonConstants.SEX_COLUMN]
                if actual_sex != expected_sex:
                    actual_sex_label = dict(Individual.SEX_CHOICES)[actual_sex]
                    errors.append("%(parent_id)s is recorded as %(actual_sex_label)s and also as the %(parent_id_type)s of %(individual_id)s" % locals())

            # is the parent in the same family?
            parent = records_by_id[parent_id]
            parent_family_id = parent.get(JsonConstants.FAMILY_ID_COLUMN) or parent['family']['familyId']
            if parent_family_id != family_id:
                errors.append("%(parent_id)s is recorded as the %(parent_id_type)s of %(individual_id)s but they have different family ids: %(parent_family_id)s and %(family_id)s" % locals())

    if fail_on_warnings:
        errors += warnings
        warnings = []
    if errors:
        raise ErrorsWarningsException(errors, warnings)
    return warnings


def parse_pedigree_table(parsed_file, filename, project=None, fail_on_warnings=False):
    """Validates and parses pedigree information from a .fam, .tsv, or Excel file.

    Args:
        parsed_file (array): The parsed output from the raw file.
        filename (string): The original filename - used to determine the file format based on the suffix.
        user (User): (optional) Django User object
        project (Project): (optional) Django Project object

    Return:
        A 3-tuple that contains:
        (
            json_records (list): list of dictionaries, with each dictionary containing info about
                one of the individuals in the input data
            errors (list): list of error message strings
            warnings (list): list of warning message strings
        )
    """

    # parse rows from file
    try:
        rows = [row for row in parsed_file[1:] if row and not (row[0] or '').startswith('#')]

        header_string = str(parsed_file[0])
        is_merged_pedigree_sample_manifest = "do not modify" in header_string.lower() and "Broad" in header_string
 
        if is_merged_pedigree_sample_manifest:
            #if not user_is_pm(user):
                #raise ValueError('Unsupported file format')
            if not project:
                raise ValueError('Project argument required for parsing sample manifest')
            # the merged pedigree/sample manifest has 3 header rows, so use the known header and skip the next 2 rows.
            headers = rows[:2]
            rows = rows[2:]

            # validate manifest_header_row1
            expected_header_columns = MergedPedigreeSampleManifestConstants.MERGED_PEDIGREE_SAMPLE_MANIFEST_COLUMN_NAMES
            expected_header_1_columns = expected_header_columns[:4] + ["Alias", "Alias"] + expected_header_columns[6:]

            expected = expected_header_1_columns
            actual = headers[0]
            if expected == actual:
                expected = expected_header_columns[4:6]
                actual = headers[1][4:6]
            unexpected_header_columns = '|'.join(difflib.unified_diff(expected, actual)).split('\n')[3:]
            if unexpected_header_columns:
                raise ValueError("Expected vs. actual header columns: {}".format("\t".join(unexpected_header_columns)))

            header = expected_header_columns
        else:
            if _is_header_row(header_string):
                header_row = parsed_file[0]
            else:
                header_row = next(
                    (row for row in parsed_file[1:] if row[0].startswith('#') and _is_header_row(','.join(row))),
                    ['family_id', 'individual_id', 'paternal_id', 'maternal_id', 'sex', 'affected']
                )
            header = [(field or '').strip('#') for field in header_row]

        for i, row in enumerate(rows):
            if len(row) != len(header):
                raise ValueError("Row {} contains {} columns: {}, while header contains {}: {}".format(
                    i + 1, len(row), ', '.join(row), len(header), ', '.join(header)
                ))

        rows = [dict(zip(header, row)) for row in rows]

    except Exception as e:
        print('Error while parsing file: {}. {}'.format(filename, e))
        #raise ErrorsWarningsException(['Error while parsing file: {}. {}'.format(filename, e)], [])

    # convert to json and validate
    try:
        '''
        if is_merged_pedigree_sample_manifest:
            logger.info("Parsing merged pedigree-sample-manifest file", user)
            rows, sample_manifest_rows, kit_id = _parse_merged_pedigree_sample_manifest_format(rows, project)
        elif 'participant_guid' in header:
            logger.info("Parsing RGP DSM export file", user)
            rows = _parse_rgp_dsm_export_format(rows)
        else:
            logger.info("Parsing regular pedigree file", user)
        '''

        json_records = _convert_fam_file_rows_to_json(rows)
    except Exception as e:
        #raise ErrorsWarningsException(['Error while converting {} rows to json: {}'.format(filename, e)], [])
        print('Error while converting {} rows to json: {}'.format(filename, e))       

    warnings = validate_fam_file_records(json_records, fail_on_warnings=fail_on_warnings)

    #if is_merged_pedigree_sample_manifest:
        #_send_sample_manifest(sample_manifest_rows, kit_id, filename, parsed_file, user, project)

    return json_records, warnings


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('--project', help='Project for tag.', required=True)
        parser.add_argument('--input', help='Project for tag.', required=True)
 
    def handle(self, *args, **options):
        project_guid = options['project']
        filename = options['input']

        f = open('/home/ubuntu/tmp/34_individuals.tsv','r')
        #contents = f.readlines()

        list_of_lists = []

        for line in f:
            inner_list = [elt.strip() for elt in line.split('\t')]
            list_of_lists.append(inner_list)

        json_records, warnings = parse_pedigree_table(list_of_lists, filename='34_individuals.tsv', project='Test')
        print(json_records)

        project = Project.objects.get(guid=project_guid)
        user = User.objects.get(id=)

        updated_individuals, updated_families, updated_notes = add_or_update_individuals_and_families(project, json_records, user)



