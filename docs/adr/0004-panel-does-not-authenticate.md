# The panel never authenticates; a credentialed timer supplies the network data

A QML-spawned process cannot receive systemd credentials, and giving it the
keyring or an auth-config file would reintroduce the plaintext we just removed
(ADR 0002). So the panel only reads a **non-secret** status document and drives
`systemctl --user`; the credential-requiring data (quota, recent files) is
produced by a short-lived credentialed oneshot (`filen-status.timer`). The cost
is an extra moving part — two producers and an API fragment — paid for zero
secrets in the UI layer and minimal credential residency (the oneshot decrypts
only for its brief run).
