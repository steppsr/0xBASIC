' Compiles and runs locally; signing and spend validation are not performed.
' Parameters are fixed into the puzzle. The solution is empty.
CONTRACT HeightLockedPayment(
    owner AS PUBLICKEY,
    recipient AS PUZZLEHASH,
    paymentAmount AS AMOUNT,
    earliestHeight AS INTEGER
)
    ASSERT AMOUNT_VALUE(paymentAmount) > 0
    ASSERT earliestHeight >= 0 AND earliestHeight <= &HFFFFFFFF
    EMIT ASSERT_MY_AMOUNT(paymentAmount)
    EMIT ASSERT_HEIGHT_ABSOLUTE(earliestHeight)
    EMIT AGG_SIG_ME(owner, PaymentMessage(owner, recipient, paymentAmount, earliestHeight))
    EMIT CREATE_COIN(recipient, paymentAmount)
END CONTRACT

FUNCTION PaymentMessage(
    owner AS PUBLICKEY,
    recipient AS PUZZLEHASH,
    paymentAmount AS AMOUNT,
    earliestHeight AS INTEGER
) AS BYTES
    DIM message AS BYTES = CONCAT(UTF8("0xBASIC/payment/v1"), 0x00)
    message = CONCAT(message, KEY_BYTES(owner))
    message = CONCAT(message, HASH_BYTES(recipient))
    message = CONCAT(message, U64BE(AMOUNT_VALUE(paymentAmount)))
    message = CONCAT(message, U32BE(earliestHeight))
    RETURN SHA256(message)
END FUNCTION
