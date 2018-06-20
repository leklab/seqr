import React from 'react'
import PropTypes from 'prop-types'
import styled from 'styled-components'
import { connect } from 'react-redux'
import { Grid } from 'semantic-ui-react'
import Timeago from 'timeago.js'
import orderBy from 'lodash/orderBy'

import PedigreeIcon from 'shared/components/icons/PedigreeIcon'
import TextFieldView from 'shared/components/panel/view-fields/TextFieldView'
import PhenotipsDataPanel from 'shared/components/panel/view-phenotips-info/PhenotipsDataPanel'
import Dataset from 'shared/components/panel/dataset'
import { HorizontalSpacer, VerticalSpacer } from 'shared/components/Spacers'
import { updateIndividual } from 'redux/rootReducer'
import { getUser } from 'redux/selectors'

import {
  CASE_REVIEW_STATUS_MORE_INFO_NEEDED,
  CASE_REVIEW_STATUS_NOT_IN_REVIEW,
  CASE_REVIEW_STATUS_OPT_LOOKUP,
  ANALYSIS_TYPE_VARIANT_CALLS,
} from '../../constants'
import { getProject, getProjectDatasets } from '../../selectors'
import CaseReviewStatusDropdown from './CaseReviewStatusDropdown'


const Detail = styled.span`
  padding: 5px 0 5px 5px;
  font-size: 11px;
  font-weight: 500;
  color: #999999;
`

const ColoredSpan = styled.span`
  color: ${props => props.color}
`

const CaseReviewDropdownContainer = styled.div`
  float: right;
  width: 220px;
`

class IndividualRow extends React.Component
{
  static propTypes = {
    user: PropTypes.object.isRequired,
    project: PropTypes.object.isRequired,
    family: PropTypes.object.isRequired,
    individual: PropTypes.object.isRequired,
    datasets: PropTypes.array.isRequired,
    updateIndividual: PropTypes.func,
    editCaseReview: PropTypes.bool,
  }

  render() {
    const { user, project, family, individual, datasets, editCaseReview } = this.props

    const { individualId, displayName, paternalId, maternalId, sex, affected, createdDate } = individual

    const caseReviewStatusOpt = CASE_REVIEW_STATUS_OPT_LOOKUP[individual.caseReviewStatus]

    let loadedDatasets = datasets.filter(dataset =>
      dataset.sampleGuids.some(sampleGuid => individual.sampleGuids.includes(sampleGuid)) &&
      dataset.analysisType === ANALYSIS_TYPE_VARIANT_CALLS &&
      dataset.isLoaded,
    )
    loadedDatasets = orderBy(loadedDatasets, [d => d.loadedDate], 'desc')

    const sampleDetails = loadedDatasets.map((dataset, i) =>
      <div key={dataset.datasetGuid}><Dataset loadedDataset={dataset} isOutdated={i !== 0} /></div>,
    )

    const individualRow = (
      <Grid stackable>
        <Grid.Row>
          <Grid.Column width={3}>
            <span>
              <div>
                <PedigreeIcon sex={sex} affected={affected} />
                &nbsp;
                {displayName || individualId}
              </div>
              <div>
                {
                  (!family.pedigreeImage && ((paternalId && paternalId !== '.') || (maternalId && maternalId !== '.'))) ? (
                    <Detail>
                      child of &nbsp;
                      <i>{(paternalId && maternalId) ? `${paternalId} and ${maternalId}` : (paternalId || maternalId) }</i>
                      <br />
                    </Detail>
                  ) : null
                }
                <Detail>
                  ADDED {new Timeago().format(createdDate).toUpperCase()}
                </Detail>
              </div>
            </span>
          </Grid.Column>
          <Grid.Column width={10}>
            {
              (editCaseReview ||
              (individual.caseReviewStatus && individual.caseReviewStatus !== CASE_REVIEW_STATUS_NOT_IN_REVIEW) ||
              (individual.caseReviewStatus === CASE_REVIEW_STATUS_MORE_INFO_NEEDED)) ?
                <div>
                  {!editCaseReview &&
                    <span>
                      <b>Case Review - Status:</b>
                      <HorizontalSpacer width={15} />
                      <ColoredSpan color={caseReviewStatusOpt ? caseReviewStatusOpt.color : 'black'}>
                        <b>{caseReviewStatusOpt ? caseReviewStatusOpt.name : individual.caseReviewStatus}</b>
                      </ColoredSpan>
                    </span>
                  }
                  {!editCaseReview && individual.caseReviewStatus === CASE_REVIEW_STATUS_MORE_INFO_NEEDED && <br />}
                  <TextFieldView
                    isVisible={
                      individual.caseReviewStatus === CASE_REVIEW_STATUS_MORE_INFO_NEEDED
                      || (editCaseReview && individual.caseReviewDiscussion) || false
                    }
                    fieldName={editCaseReview ? 'Case Review Discussion' : 'Discussion'}
                    field="caseReviewDiscussion"
                    idField="individualGuid"
                    initialValues={individual}
                    modalTitle={`Case Review Discussion for Individual ${individual.individualId}`}
                    onSubmit={this.props.updateIndividual}
                  />
                  <VerticalSpacer height={10} />
                </div>
                : null
            }
            <TextFieldView
              isEditable={(user.is_staff || project.canEdit) && !editCaseReview}
              fieldName="Individual Notes"
              field="notes"
              idField="individualGuid"
              initialValues={individual}
              modalTitle={`Notes for Individual ${individual.individualId}`}
              onSubmit={this.props.updateIndividual}
            />
            <PhenotipsDataPanel
              individual={individual}
              showDetails
              showEditPhenotipsLink={project.canEdit && !editCaseReview}
            />
          </Grid.Column>
          <Grid.Column width={3}>
            {
              editCaseReview ?
                <CaseReviewDropdownContainer>
                  <CaseReviewStatusDropdown individual={individual} />
                  {
                    individual.caseReviewStatusLastModifiedDate ? (
                      <Detail>
                        <HorizontalSpacer width={5} />
                        CHANGED ON {new Date(individual.caseReviewStatusLastModifiedDate).toLocaleDateString()}
                        { individual.caseReviewStatusLastModifiedBy && ` BY ${individual.caseReviewStatusLastModifiedBy}` }
                      </Detail>
                    ) : null
                  }
                </CaseReviewDropdownContainer> : sampleDetails
            }
          </Grid.Column>
        </Grid.Row>
      </Grid>)

    return individualRow
  }
}

export { IndividualRow as IndividualRowComponent }

const mapStateToProps = state => ({
  user: getUser(state),
  project: getProject(state),
  datasets: getProjectDatasets(state),
})

const mapDispatchToProps = {
  updateIndividual,
}

export default connect(mapStateToProps, mapDispatchToProps)(IndividualRow)
