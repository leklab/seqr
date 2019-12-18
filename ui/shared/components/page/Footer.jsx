import React from 'react'
import PropTypes from 'prop-types'
import styled from 'styled-components'
import { Table } from 'semantic-ui-react'
import { connect } from 'react-redux'

import { getVersion } from 'redux/selectors'

const TableHeaderCell = styled(Table.HeaderCell)`
  border-radius: 0 !important;
  font-weight: normal !important;
  
  &.disabled {
    color: grey !important;
  }
`

const Footer = ({ version }) =>
  <Table>
    <Table.Header>
      <Table.Row>
        <TableHeaderCell width={1} />
        <TableHeaderCell width={2} disabled>seqr {version}</TableHeaderCell>
        <TableHeaderCell width={6}>
          For bug reports or feature requests please submit  &nbsp;
          <a href="https://github.com/macarthur-lab/seqr/issues">Github Issues</a>
        </TableHeaderCell>
        <TableHeaderCell width={5} textAlign="right">
          If you have questions or feedback, &nbsp;
          <a
            href="https://mail.google.com/mail/?view=cm&amp;fs=1&amp;tf=1&amp;to=seqr@broadinstitute.org"
            target="_blank"
          >
            Contact Us
          </a>
        </TableHeaderCell>
        <TableHeaderCell width={2} />
      </Table.Row>
    </Table.Header>
  </Table>

Footer.propTypes = {
  version: PropTypes.string,
}

const mapStateToProps = state => ({
  version: getVersion(state),
})

export default connect(mapStateToProps)(Footer)
