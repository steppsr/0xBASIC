' Local compilation/execution fixture; signing and spend acceptance are separate.
CONTRACT PaymentChange(
    owner AS PUBLICKEY,
    recipient AS PUZZLEHASH,
    changeRecipient AS PUZZLEHASH,
    inputAmount AS AMOUNT
)
    SOLUTION paymentAmount AS AMOUNT
    ASSERT AMOUNT_VALUE(inputAmount) > 0
    ASSERT AMOUNT_VALUE(paymentAmount) > 0
    ASSERT AMOUNT_VALUE(paymentAmount) <= AMOUNT_VALUE(inputAmount)
    ASSERT recipient <> changeRecipient
    DIM change AS INTEGER = AMOUNT_VALUE(inputAmount) - AMOUNT_VALUE(paymentAmount)
    EMIT ASSERT_MY_AMOUNT(inputAmount)
    EMIT AGG_SIG_ME(owner, PaymentChangeMessage(owner, recipient, changeRecipient, inputAmount, paymentAmount))
    EMIT CREATE_COIN(recipient, paymentAmount)
    IF change > 0 THEN
        EMIT CREATE_COIN(changeRecipient, AS_AMOUNT(change))
    END IF
END CONTRACT

FUNCTION PaymentChangeMessage(
    owner AS PUBLICKEY,
    recipient AS PUZZLEHASH,
    changeRecipient AS PUZZLEHASH,
    inputAmount AS AMOUNT,
    paymentAmount AS AMOUNT
) AS BYTES
    DIM message AS BYTES = CONCAT(UTF8("0xBASIC/payment-change/v1"), 0x00)
    message = CONCAT(message, KEY_BYTES(owner))
    message = CONCAT(message, HASH_BYTES(recipient))
    message = CONCAT(message, HASH_BYTES(changeRecipient))
    message = CONCAT(message, U64BE(AMOUNT_VALUE(inputAmount)))
    message = CONCAT(message, U64BE(AMOUNT_VALUE(paymentAmount)))
    RETURN SHA256(message)
END FUNCTION
