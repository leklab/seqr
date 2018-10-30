import React from 'react'
import { Tab } from 'semantic-ui-react'
import styled from 'styled-components'
import Modal from 'shared/components/modal/Modal'
import { EditIndividualsBulkForm, EditHPOBulkForm } from './BulkEditForm'
import EditIndividualsForm from './EditIndividualsForm'
import EditFamiliesForm from './EditFamiliesForm'

const TabPane = styled(Tab.Pane)`
  padding: 1em 0 !important;
`

const MODAL_NAME = 'editFamiliesAndIndividuals'
const PANE_DETAILS = [
  {
    menuItem: 'Edit Families',
    formClass: EditFamiliesForm,
  },
  {
    menuItem: 'Edit Individuals',
    formClass: EditIndividualsForm,
  },
  {
    menuItem: 'Edit HPO Terms',
    formClass: EditHPOBulkForm,
  },
  {
    menuItem: 'Bulk Upload',
    formClass: EditIndividualsBulkForm,
  },
]
const PANES = PANE_DETAILS.map(({ formClass, menuItem }) => ({
  pane: <TabPane key={menuItem}>{React.createElement(formClass, { modalName: MODAL_NAME })}</TabPane>,
  menuItem,
}))

export default () => (
  <Modal
    modalName={MODAL_NAME}
    title="Edit Families & Individuals"
    size="large"
    trigger={
      <div style={{ display: 'inline-block' }}>
        <a role="button" tabIndex="0" style={{ cursor: 'pointer' }}>
          Edit Families & Individuals
        </a>
      </div>
    }
  >
    <Tab
      renderActiveOnly={false}
      panes={PANES}
    />
  </Modal>

)

