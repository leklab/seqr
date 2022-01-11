import React from 'react'
import PropTypes from 'prop-types'
import { connect } from 'react-redux'

import { navigateSavedHashedSearch } from 'redux/rootReducer'
import { VEP_GROUP_SV, ANY_AFFECTED } from 'shared/utils/constants'
import { ButtonLink } from '../StyledComponents'

const SearchResultsLink = ({
  buttonText = 'Gene Search', openSearchResults, initialSearch, variantId, location, genomeVersion, svType,
  familyGuids, familyGuid, projectFamilies, inheritanceMode, ...props
}) => <ButtonLink {...props} content={buttonText} onClick={openSearchResults} />

SearchResultsLink.propTypes = {
  buttonText: PropTypes.string,
  initialSearch: PropTypes.object,
  location: PropTypes.string,
  variantId: PropTypes.string,
  genomeVersion: PropTypes.string,
  svType: PropTypes.string,
  familyGuid: PropTypes.string,
  familyGuids: PropTypes.arrayOf(PropTypes.string),
  projectFamilies: PropTypes.arrayOf(PropTypes.object),
  openSearchResults: PropTypes.func,
  inheritanceMode: PropTypes.string,
}

const mapDispatchToProps = (dispatch, ownProps) => ({
  openSearchResults: () => {
    const search = {
      ...(ownProps.initialSearch || {}),
      locus: {
        rawItems: ownProps.location, rawVariantItems: ownProps.variantId, genomeVersion: ownProps.genomeVersion,
      },
    }
    if (ownProps.svType) {
      search.annotations = { [VEP_GROUP_SV]: [ownProps.svType] }
    }
    if (ownProps.inheritanceMode) {
      search.inheritance = { mode: ownProps.inheritanceMode }
    }
    const familyGuids = ownProps.familyGuid ? [ownProps.familyGuid] : ownProps.familyGuids
    const projectFamilies = familyGuids ? [{ familyGuids }] : ownProps.projectFamilies
    dispatch(navigateSavedHashedSearch(
      { allProjectFamilies: !projectFamilies, projectFamilies, search },
      resultsLink => window.open(resultsLink, '_blank'),
    ))
  },
})

const ConnectedSearchResultsLink = connect(null, mapDispatchToProps)(SearchResultsLink)

export default ConnectedSearchResultsLink

export const GeneSearchLink = props => <ConnectedSearchResultsLink inheritanceMode={ANY_AFFECTED} {...props} />
