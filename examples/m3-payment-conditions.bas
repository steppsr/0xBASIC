REM Condition construction example; signature authorization is not included.
CONTRACT PaymentConditions(recipient AS PUZZLEHASH, paymentAmount AS AMOUNT, earliestHeight AS INTEGER)
EMIT ASSERT_MY_AMOUNT(paymentAmount)
EMIT ASSERT_HEIGHT_ABSOLUTE(earliestHeight)
DIM outputs AS LIST OF CONDITION = [Payment(recipient, paymentAmount)]
EMIT FIRST(outputs)
END CONTRACT

FUNCTION Payment(destination AS PUZZLEHASH, value AS AMOUNT) AS CONDITION
RETURN CREATE_COIN(destination, value)
END FUNCTION
