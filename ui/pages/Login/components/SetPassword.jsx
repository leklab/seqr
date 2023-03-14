import React from 'react'
import PropTypes from 'prop-types'
import { connect } from 'react-redux'
import queryString from 'query-string'
// import { validators } from 'shared/components/form/FormHelpers'

import { USER_NAME_FIELDS } from 'shared/utils/constants'

import { setPassword } from '../reducers'
// import { setPassword, login } from '../reducers'
import { getNewUser } from '../selectors'
import UserFormLayout from './UserFormLayout'
// import { UserFormContainer, UserForm } from './UserFormLayout'
// import { UserFormContainer } from './UserFormLayout'

const minLengthValidate = value => ((value && value.length > 7 && value.length < 128) ? undefined : 'Password must be at between 8-128 characters')

const samePasswordValidate = (value, allValues) => (value === allValues.password ? undefined : 'Passwords do not match')

const PASSWORD_FIELDS = [
  {
    name: 'password',
    label: 'Password',
    validate: minLengthValidate,
    type: 'password',
    width: 16,
    inline: true,
  },
  {
    name: 'passwordConfirm',
    label: 'Confirm Password',
    validate: samePasswordValidate,
    type: 'password',
    width: 16,
    inline: true,
  },
]

const FIELDS = [...PASSWORD_FIELDS, ...USER_NAME_FIELDS]

// const dummy = () => ({})
/*
const FIELDS = [
  { name: 'email', label: 'Email', validate: validators.required },
  { name: 'password', label: 'Password', type: 'password', validate: validators.required },
]
*/

const SetPassword = ({ onSubmit, newUser, location }) => {
  const isReset = queryString.parse(location.search).reset
  console.log('In setPassword function')
  console.log(onSubmit)
  console.log(isReset)
  console.log(newUser)
  console.log('Changed the form')
  console.log('Added dummy')
  /*
  return (
    <UserFormContainer header="Login to seqr">
      Some text
    </UserFormContainer>
  )
  */
  /*
  return (
    <UserFormContainer header="Login to seqr">
      <UserForm
        onSubmit={dummy}
        modalName="login"
        fields={FIELDS}
        submitButtonText="Log In"
      />
    </UserFormContainer>
  )
  */
  return (
    <UserFormLayout
      header={isReset ? 'Reset password' : 'Welcome to seqr'}
      subheader={isReset ? '' : 'Fill out this form to finish setting up your account'}
      onSubmit={onSubmit}
      modalName="set-password"
      fields={isReset ? PASSWORD_FIELDS : FIELDS}
      initialValues={newUser}
    />
  )
}

SetPassword.propTypes = {
  location: PropTypes.object,
  newUser: PropTypes.object,
  onSubmit: PropTypes.func,
}

const mapStateToProps = state => ({
  newUser: getNewUser(state),
})

/*
const mapDispatchToProps = (dispatch, ownProps) => ({
  onSubmit: updates => dispatch(setPassword({ ...updates, ...ownProps.match.params })),
})
*/

const mapDispatchToProps = (dispatch, ownProps) => {
  return {
    onSubmit: (updates) => {
      return dispatch(setPassword({ ...updates, ...ownProps.match.params }))
    },
  }
}

export default connect(mapStateToProps, mapDispatchToProps)(SetPassword)
