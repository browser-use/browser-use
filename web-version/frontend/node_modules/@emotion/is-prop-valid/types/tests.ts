import isPropValid from '@emotion/is-prop-valid'

isPropValid('ref')

// $ExpectError
isPropValid()
// $ExpectError
isPropValid(5)
// $ExpectError
isPropValid({})
// $ExpectError
isPropValid('ref', 'def')
