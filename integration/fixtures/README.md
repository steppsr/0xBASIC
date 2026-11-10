# Public TLS test fixtures

These certificates and unencrypted private keys are deliberately public fixtures for a loopback-only fake RPC server and client. Never configure a real Chia service to trust this CA or use these keys. They contain no user/node credentials.

RSA2048 certificates were generated for this test suite with SHA256 signatures, validity2020-01-01 through2040-01-01, a CA basic constraint, and separate serverAuth/clientAuth leaf extensions. The wrong-ca certificate has a different key. The CA private keys were not saved. Tests need only Python's standard library; generation used the already-installed cryptography package, with no dependency change.

The server certificate deliberately has a non-hostname common name, exercising the reviewed Chia private-CA behavior: hostname matching disabled while chain verification and mutual client authentication remain required. The fixture server binds only127.0.0.1 on an ephemeral port and shuts down after tests.
